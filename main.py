
import os
import threading
import io
import csv
import math
import time
import pandas as pd
import math
from datetime import datetime
import json
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
try:
    import pyvisa
except Exception:
    pyvisa = None
from Keithley2602 import Keithley2602
import copy

app = Flask(__name__, static_folder="static", template_folder="templates")

# Shared state for instrument connection and uploads
class State:
    def __init__(self):
        # instruments dict keyed by instrument id -> {'obj': instance, 'smus': {...}}
        self.instruments = {}
        self.upload = None
        self.uploads = []
        self._next_upload_id = 1
        # DataFrame to store streaming samples. Start with ts and SMU A/B cols
        self.stream_df = pd.DataFrame(columns=['ts'])

    def new_upload_id(self):
        uid = self._next_upload_id
        self._next_upload_id += 1
        return uid
state = State()

# global start time for streaming; set when stream begins first time
t0 = None


@app.route("/")
def index():
    return render_template("index.html")


def parse_csv_text(text):
    # Try to sniff dialect and header
    sample = text[:4096]
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample)
    except Exception:
        dialect = csv.excel

    has_header = False
    try:
        has_header = sniffer.has_header(sample)
    except Exception:
        has_header = False

    f = io.StringIO(text)
    if has_header:
        reader = csv.DictReader(f, dialect=dialect)
        headers = reader.fieldnames
        rows = list(reader)
    else:
        reader = csv.reader(f, dialect=dialect)
        rows_list = list(reader)
        if not rows_list:
            headers = []
            rows = []
        else:
            ncols = max(len(r) for r in rows_list)
            headers = [f"col{i}" for i in range(ncols)]
            rows = [ {headers[i]: (r[i] if i < len(r) else "") for i in range(ncols)} for r in rows_list ]

    # Build columns and coerce to numbers where possible, else null
    columns = {h: [] for h in headers}
    for r in rows:
        for h in headers:
            val = r.get(h, "")
            if val is None:
                columns[h].append(None)
                continue
            s = str(val).strip()
            if s == "":
                columns[h].append(None)
                continue
            try:
                num = float(s)
                columns[h].append(num)
            except Exception:
                columns[h].append(None)

    # Detect if there is an index-like column (integer sequence with step 1)
    nrows = len(rows)
    def is_index_column(col):
        if not col or len(col) != nrows:
            return False
        # must have no missing values
        for v in col:
            if v is None:
                return False
            if not isinstance(v, (int, float)):
                return False
            if math.isnan(v):
                return False
        # all integer valued
        ints = [int(round(x)) for x in col]
        for a, b in zip(col, ints):
            if not math.isclose(a, b):
                return False
        # check step 1 progression
        if nrows <= 1:
            return True
        diffs = [ints[i+1] - ints[i] for i in range(len(ints)-1)]
        if all(d == 1 for d in diffs) and (ints[0] in (0, 1)):
            return True
        return False

    found_index = False
    for h in headers:
        if is_index_column(columns.get(h, [])):
            found_index = True
            break

    if not found_index:
        # create an index column starting at 0
        idx_name = 'index'
        # avoid name collision
        i = 0
        while idx_name in columns:
            i += 1
            idx_name = f'index{i}'
        columns = {idx_name: [float(i) for i in range(nrows)], **columns}
        headers = [idx_name] + headers

    return {"headers": headers, "columns": columns, "rows_count": nrows}


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400
    f = request.files["file"]
    text = f.read().decode("utf-8", errors="replace")
    parsed = parse_csv_text(text)
    # Build upload object and ArrayData entries
    upload_id = state.new_upload_id()
    upload = {
        "id": upload_id,
        "filename": f.filename,
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "raw_text": text,
        "rows_count": parsed["rows_count"],
        "columns": []  # list of column objects
    }

    for h in parsed["headers"]:
        col = {
            "name": h,
            "original_name": h,
            "array": parsed["columns"].get(h, []),
            "header_info": {},
        }
        upload["columns"].append(col)

    state.uploads.append(upload)
    # persist
    try:
        save_state_to_disk()
    except Exception:
        pass

    return jsonify({"ok": True, 
                    "parsed": {
                        "id": upload_id, 
                        "filename": upload["filename"],
                        "rows_count": upload["rows_count"],
                        "headers": [c["name"] for c in upload["columns"]]}})


@app.route('/stream')
def stream():
    def gen():
        global t0
        if t0 is None:
            t0 = time.time()
        while True:
            payload = {'ts': time.time() - t0, 'data': {'a': {'v': None, 'i': None}, 'b': {'v': None, 'i': None}}}
            a_v = a_i = b_v = b_i = None
            if state.instruments:
                # pick the first instrument in the dict
                inst_entry = next(iter(state.instruments.values()))
                inst_obj = inst_entry['obj'] if isinstance(inst_entry, dict) else inst_entry
                inst_smus = inst_entry.get('smus') if isinstance(inst_entry, dict) else None
                # get a measurement dict from the instrument
                try:
                    meas = inst_obj.measure() or {}
                except Exception:
                    meas = {'A_v': None, 'A_i': None, 'B_v': None, 'B_i': None}
                # Only include values for SMUs whose output is ON (per-instrument if available)
                for k in ('A', 'B'):
                    cfg = (inst_smus.get(k) if inst_smus and k in inst_smus else state.smus.get(k, {}))
                    key_v = f"{k}_v"
                    key_i = f"{k}_i"
                    if not cfg.get('output'):
                        payload['data'][k.lower()]['v'] = None
                        payload['data'][k.lower()]['i'] = None
                        continue
                    vv = meas.get(key_v)
                    ii = meas.get(key_i)
                    payload['data'][k.lower()]['v'] = vv
                    payload['data'][k.lower()]['i'] = ii
                a_v = payload['data']['a'].get('v')
                a_i = payload['data']['a'].get('i')
                b_v = payload['data']['b'].get('v')
                b_i = payload['data']['b'].get('i')
            else:
                payload['error'] = 'no instrument'

            # Append the sampled row to the in-memory DataFrame
            try:
                # ensure DataFrame has the expected columns, add if necessary
                cols = ['ts', 'A_v', 'A_i', 'B_v', 'B_i']
                for c in cols:
                    if c not in state.stream_df.columns:
                        state.stream_df[c] = pd.NA
                row = { 'ts': payload['ts'], 'A_v': a_v, 'A_i': a_i, 'B_v': b_v, 'B_i': b_i }
                state.stream_df = pd.concat([state.stream_df, pd.DataFrame([row])], ignore_index=True)
            except Exception:
                # be defensive: if append fails, continue without crashing the generator
                pass

            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(0.5)
    return Response(stream_with_context(gen()), mimetype='text/event-stream')


@app.route("/api/data", methods=["GET"])
def api_data():
    # Return summary of current uploads (filenames and header names)
    summaries = []
    for u in state.uploads:
        summaries.append({
            "id": u["id"],
            "filename": u.get("filename"),
            "rows_count": u.get("rows_count"),
            "headers": [c["name"] for c in u.get("columns", [])]
        })
    return jsonify({"uploads": summaries})


@app.route("/api/full", methods=["GET"])
def api_full():
    # Return full uploads including arrays (may be large)
    return jsonify({"uploads": state.uploads})


@app.route("/plot")
def plot_page():
    return render_template("plot.html")


@app.route("/connect")
def acquire_page():
    return render_template("connect.html")


@app.route("/api/rename", methods=["POST"])
def api_rename():
    j = request.get_json() or {}
    upload_id = j.get("upload_id")
    old_name = j.get("old_name")
    new_name = j.get("new_name")
    if not upload_id or not old_name or new_name is None:
        return jsonify({"error": "upload_id, old_name and new_name required"}), 400

    for u in state.uploads:
        if u.get("id") == upload_id:
            for col in u.get("columns", []):
                if col.get("name") == old_name:
                    col["name"] = new_name
                    try:
                        save_state_to_disk()
                    except Exception:
                        pass
                    return jsonify({"ok": True})
            return jsonify({"error": "Column not found. Try refreshing."}), 404
    return jsonify({"error": "upload not found"}), 404


def save_state_to_disk():
    data = {"uploads": state.uploads, "next_upload_id": state._next_upload_id, "smus": state.smus}
    p = os.path.join(os.path.dirname(__file__), "data_store.json")
    with open(p, "w", encoding="utf-8") as fo:
        json.dump(data, fo, indent=2)


def load_state_from_disk():
    p = os.path.join(os.path.dirname(__file__), "data_store.json")
    if not os.path.exists(p):
        return
    with open(p, "r", encoding="utf-8") as fi:
        data = json.load(fi)
    state.uploads = data.get("uploads", [])
    state._next_upload_id = data.get("next_upload_id", state._next_upload_id)


@app.route('/api/force_update', methods=['POST'])
def api_force_update():
    # Trigger an immediate measurement from the first instrument and append to stream_df
    if not state.instruments:
        return jsonify({'error': 'no instrument'}), 404
    inst_entry = next(iter(state.instruments.values()))
    inst_obj = inst_entry['obj'] if isinstance(inst_entry, dict) else inst_entry
    inst_smus = inst_entry.get('smus') if isinstance(inst_entry, dict) else None
    try:
        meas = inst_obj.measure() or {}
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Build payload for both SMUs, honoring per-instrument output flags
    payload = {'ts': time.time(), 'meas': {}}
    for k in ('A', 'B'):
        cfg = (inst_smus.get(k) if inst_smus and k in inst_smus else state.smus.get(k, {}))
        if not cfg.get('output'):
            payload['meas'][f'{k}_v'] = None
            payload['meas'][f'{k}_i'] = None
            continue
        payload['meas'][f'{k}_v'] = meas.get(f'{k}_v')
        payload['meas'][f'{k}_i'] = meas.get(f'{k}_i')

    # Append to DataFrame, creating missing columns if needed
    try:
        cols = ['ts', 'A_v', 'A_i', 'B_v', 'B_i']
        for c in cols:
            if c not in state.stream_df.columns:
                state.stream_df[c] = pd.NA
        row = { 'ts': payload['ts'], 'A_v': payload['meas'].get('A_v'), 'A_i': payload['meas'].get('A_i'), 'B_v': payload['meas'].get('B_v'), 'B_i': payload['meas'].get('B_i') }
        state.stream_df = pd.concat([state.stream_df, pd.DataFrame([row])], ignore_index=True)
    except Exception:
        pass

    return jsonify({'ok': True, 'meas': payload})


@app.route('/api/instrument/add', methods=['POST'])
def api_instrument_add(): 
    j = request.get_json() or {}
    typ = j.get('type')
    if typ == 'keithley2602' or typ == 'keithley':
        k = Keithley2602()
        iid = f'keithley{len(state.instruments)+1}'
        state.instruments[iid] = {'obj': k}
        return jsonify({'ok': True, 'id': iid, 'type': 'keithley2602'})
    return jsonify({'error': 'unknown type'}), 400


@app.route('/api/instruments', methods=['GET'])
def api_instruments_list():
    out = []
    for iid, entry in state.instruments.items():
        inst = entry.get('obj') if isinstance(entry, dict) else entry
        tname = getattr(inst, '__class__', type(inst)).__name__
        out.append({'id': iid, 'type': tname})
    return jsonify({'instruments': out})


@app.route('/api/instrument/<iid>/card', methods=['GET'])
def api_instrument_card(iid):
    entry = state.instruments.get(iid)
    if not entry:
        return jsonify({'error': 'not found'}), 404
    inst = entry.get('obj') if isinstance(entry, dict) else entry
    type_name = None
    # try to infer a type name
    if isinstance(entry, dict) and entry.get('smus') is not None:
        type_name = getattr(inst, '__class__', type(inst)).__name__
    try:
        html = inst.card_html(iid, type_name=type_name)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'html': html})


@app.route('/api/instrument/<iid>/open', methods=['POST'])
def api_instrument_open(iid):
    entry = state.instruments.get(iid)
    if not entry:
        return jsonify({'error': 'not found'}), 404
    inst = entry['obj'] if isinstance(entry, dict) else entry
    try:
        ok = inst.open()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    if ok:
        return jsonify({'ok': True, 'status': 'opened', 'idn': getattr(inst, 'idn', None)})
    else:
        return jsonify({'ok': False, 'status': 'open failed'}), 500


@app.route('/api/instrument/<iid>/close', methods=['POST'])
def api_instrument_close(iid):
    entry = state.instruments.get(iid)
    if not entry:
        return jsonify({'error': 'not found'}), 404
    inst = entry['obj'] if isinstance(entry, dict) else entry
    try:
        inst.close()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True})


@app.route('/api/instrument/<iid>', methods=['DELETE'])
def api_instrument_delete(iid):
    entry = state.instruments.get(iid)
    if not entry:
        return jsonify({'error': 'not found'}), 404
    inst = entry['obj'] if isinstance(entry, dict) else entry
    try:
        inst.close()
    except Exception:
        pass
    state.instruments[iid] = None
    return jsonify({'ok': True})


@app.route('/api/instrument/<iid>/update', methods=['GET', 'POST'])
def api_instrument_update(iid):
    entry = state.instruments.get(iid)
    if not entry:
        return jsonify({'error': 'not found'}), 404

    inst = entry.get('obj') if isinstance(entry, dict) else entry

    if request.method == 'GET':
        # Return the flat stored settings and any instrument-provided options.
        # The instrument is responsible for exposing its own option lists.
        settings = getattr(inst, 'settings', {}) or {}
        return jsonify({'settings': settings})

    data = request.get_json() or {}

    try:
        res = inst.update(data)
        # If update returns a dict, send it back; otherwise just acknowledge
        if isinstance(res, dict):
            return jsonify(res)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    load_state_from_disk()
    app.run(host="0.0.0.0", port=5000, debug=True)


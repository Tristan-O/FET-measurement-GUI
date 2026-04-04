
import os
import threading
import io
import csv
import math
import time
import pandas as pd
import numpy as np
import math
from datetime import datetime
import json
from collections import OrderedDict
from Sweep import StopSweep
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
from Keithley2602 import Keithley2602
from Keithley6430 import Keithley6430
from NotesInstrument import NotesInstrument

app = Flask(__name__, static_folder="static", template_folder="templates")
BASE_DIR = os.path.dirname(__file__)
TEMP_DIR = os.path.join(os.path.join(BASE_DIR, "temp"), time.strftime('%Y-%m-%d'))
DATA_DIR = os.path.join(os.path.join(BASE_DIR, "data"), time.strftime('%Y-%m-%d'))

# Shared state for instrument connection and uploads
class State:
    def __init__(self):
        # instruments dict keyed by instrument id -> {'obj': instance, 'smus': {...}}
        self.instruments = OrderedDict()
        self.upload = None
        self.uploads = []
        self._next_upload_id = 1
        # DataFrame to store streaming samples. Start with ts and SMU A/B cols
        self.stream_df = pd.DataFrame()
        # streaming control flag
        self.streaming = False
        self.measure_thread:PausableThread = None
        # incremented whenever stream data is cleared so SSE clients can refresh
        self.stream_clear_generation = 0
    def new_upload_id(self):
        uid = self._next_upload_id
        self._next_upload_id += 1
        return uid
state = State()


def build_stream_upload(df: pd.DataFrame):
    """Build the synthetic stream upload object used by /api/full and SSE refresh packets."""
    if df is None or len(df.columns) == 0:
        return {
            "id": 0,
            "filename": "",
            "uploaded_at": None,
            "raw_text": None,
            "rows_count": 0,
            "columns": [{"name": 'index', "original_name": 'index', "array": [], "header_info": {}}]
        }

    cols = [{"name": 'index', "original_name": 'index', "array": df.index.to_list(), "header_info": {}}]
    for c in df.columns:
        cols.append({"name": c, "original_name": c, "array": df[c].tolist(), "header_info": {}})
    return {
        "id": 0,
        "filename": "",
        "uploaded_at": None,
        "raw_text": None,
        "rows_count": len(df),
        "columns": cols
    }

class PausableThread(threading.Thread):
    t0 = None
    rate_limit = 100
    def __init__(self, args=(), kwargs=None):
        super().__init__()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Initially set, so thread runs immediately
        self._stop_event = threading.Event()
        self._stop_event.set()  # Initially set, so thread will not stop immediately
        self.args = args
        self.kwargs = kwargs if kwargs is not None else {}
    def run(self):
        iter_num = 0
        if PausableThread.t0 is None:
            t1 = PausableThread.t0 = time.time() 
        os.makedirs(TEMP_DIR, exist_ok=True)
        csv_path = os.path.join(TEMP_DIR, time.strftime('%Y-%m-%d_%H%M%S')+'_raw.csv')
        last_written_row = 0
        while True:
            # The thread waits here if the event is cleared
            self._pause_event.wait() 

            # Check for a stop condition

            if not self._stop_event.is_set(): 
                for k,instr in state.instruments.items():
                    try:
                        instr['obj'].start()
                    except:
                        pass
                self.pause(True)
                self._stop_event.set()
                continue

            # Rate limiting - no less than 10ms can elapse between data points
            try:
                time.sleep((t1 + 1/self.rate_limit) - time.time()) # Use time.sleep() to control loop speed
            except ValueError:
                pass

            # --- Thread's work goes here ---
            t = time.time()
            res = {'ts':t, 'delta time':t-PausableThread.t0}
            for k,instr in state.instruments.items():
                try:
                    res_ = instr['obj'].next()
                except StopSweep:
                    self.stop()
                    res = {}
                    break
                res_ = {f'{k}.{k2}':e2 for k2,e2 in res_.items()}
                res.update(res_)

            for k in res:
                if k not in state.stream_df.columns:
                    state.stream_df[k] = None
            if res:
                state.stream_df.loc[len(state.stream_df)] = res

            # Persist the newest row to CSV every nth iteration.
            if iter_num % 10 == 9 or not self._stop_event.is_set() or not self._pause_event.is_set():
                try:
                    # Keep unwritten rows pending so transient file-write failures
                    # do not lose samples.
                    new_df = state.stream_df.iloc[last_written_row:].copy()
                    if new_df.empty:
                        iter_num += 1
                        continue

                    # Flatten pandas/numpy scalars for stable CSV output.
                    new_df = new_df.where(~new_df.isna(), None)
                    for col in new_df.columns:
                        new_df[col] = new_df[col].map(lambda x: x.item() if hasattr(x, 'item') else x)

                    new_df.to_csv(
                        csv_path,
                        mode='a',
                        header=last_written_row==0,
                        index=False
                    )
                    last_written_row += len(new_df)
                except Exception as e:
                    print('ERROR: Unable to append newest stream row to CSV:', e)

            iter_num += 1
            t1 = time.time()
    def pause(self, pause=None):
        """Pause the thread's execution."""
        if pause is None:
            pause = self._pause_event.is_set()
        
        if pause:
            self._pause_event.clear() # Clear the flag, causing wait() to block
        else:
            self._pause_event.set()
    def resume(self):
        """Resume the thread's execution."""
        self._pause_event.set() # Set the flag, unblocking wait()
    def stop(self):
        self._stop_event.clear()
        self._pause_event.set()


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


@app.route('/api/measure/stream')
def stream():
    def gen():
        last = len(state.stream_df)
        last_clear_generation = state.stream_clear_generation
        while True:
            try:
                # If data was cleared, notify clients to clear/refresh plots and
                # include a full replacement stream payload.
                if state.stream_clear_generation != last_clear_generation:
                    payload = {
                        'clear': True,
                        'refresh': True,
                        'generation': state.stream_clear_generation,
                        'full': build_stream_upload(state.stream_df)
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    last_clear_generation = state.stream_clear_generation
                    last = len(state.stream_df)

                ln = len(state.stream_df)
                if ln > last:
                    # yield new rows one by one as SSE
                    for i in range(last, ln):
                        row = state.stream_df.iloc[i].to_dict()
                        # convert pandas NA to None / python scalars
                        clean = {}
                        for k, v in row.items():
                            try:
                                if pd.isna(v):
                                    clean[k] = None
                                elif hasattr(v, 'item'):
                                    clean[k] = v.item()
                                else:
                                    clean[k] = v
                            except Exception:
                                clean[k] = v
                        clean['index'] = i
                        yield f"data: {json.dumps(clean)}\n\n"
                    last = ln
                time.sleep(0.2)
            except GeneratorExit:
                break
            except Exception:
                time.sleep(0.5)
    return Response(stream_with_context(gen()), mimetype='text/event-stream')


@app.route('/api/measure/start', methods=['POST'])
def api_measure_start():
    if state.measure_thread is not None:
        e = 'ERROR: Measurement thread cannot start, as it was never stopped!'
        print(e)
        return jsonify({'error': str(e)}), 500
    state.measure_thread = PausableThread()
    for _,instr in state.instruments.items():
        instr['obj'].start()
    state.measure_thread.start()
    return jsonify({'ok': True})


@app.route('/api/measure/pause', methods=['POST'])
def api_measure_pause():
    if state.measure_thread is None:
        e = 'ERROR: Measurement thread cannot pause, as it was never started!'
        print(e)
        return jsonify({'error': str(e)}), 500
    state.measure_thread.pause()
    return jsonify({'ok': True})


@app.route('/api/measure/stop', methods=['POST'])
def api_measure_stop():
    if state.measure_thread is None:
        e = 'ERROR: Measurement thread cannot stop, as it was never started!'
        print(e)
        return jsonify({'error': str(e)}), 500
    state.measure_thread.stop()
    # state.measure_thread.join()
    # state.measure_thread = None
    return jsonify({'ok': True})


@app.route('/api/measure/save', methods=['POST'])
def api_measure_save():
    j = request.get_json() or {}
    notes = (j.get('notes') or '').strip()
    ts = time.strftime('%Y-%m-%d_%H%M%S')

    if state.stream_df is None or state.stream_df.empty:
        return jsonify({'error': 'No streaming data to save'}), 400

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, f'{ts}_measurement.xlsx')

    # Build instrument settings sheet rows
    settings_rows = []
    for iid, entry in state.instruments.items():
        if not entry:
            continue
        inst = entry.get('obj') if isinstance(entry, dict) else entry
        if inst is None:
            continue
        tname = getattr(inst, '__class__', type(inst)).__name__
        st = getattr(inst, 'status', None)
        idn = getattr(inst, 'idn', None)
        settings = getattr(inst, 'settings', {}) or {}
        if settings:
            for k, v in settings.items():
                settings_rows.append({
                    'instrument_id': iid,
                    'instrument_type': tname,
                    'status': st,
                    'idn': idn,
                    'setting_key': k,
                    'setting_value': v
                })
        else:
            settings_rows.append({
                'instrument_id': iid,
                'instrument_type': tname,
                'status': st,
                'idn': idn,
                'setting_key': None,
                'setting_value': None
            })

    notes_df = pd.DataFrame([{
        'saved_time': time.strftime('%Y-%m-%d_%H%M%S'),
        'notes': notes,
        'rows_saved': len(state.stream_df)
    }])
    settings_df = pd.DataFrame(settings_rows)
    data_df = state.stream_df.copy()

    try:
        with pd.ExcelWriter(out_path) as writer:
            data_df.to_excel(writer, sheet_name='stream_data', index=False)
            notes_df.to_excel(writer, sheet_name='notes', index=False)
            settings_df.to_excel(writer, sheet_name='instrument_settings', index=False)
    except Exception as e:
        return jsonify({'error': f'Unable to save xlsx: {e}'}), 500

    return jsonify({'ok': True, 'file': os.path.relpath(out_path, BASE_DIR)})


@app.route('/api/measure/clear', methods=['POST'])
def api_measure_clear():
    state.stream_df = pd.DataFrame(columns=state.stream_df.columns)
    state.stream_clear_generation += 1
    return jsonify({'ok': True})


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
    # Also include in-memory streaming data (`state.stream_df`) as a synthetic upload
    uploads = list(state.uploads)
    try:
        if len(state.stream_df.columns) > 0:
            stream_upload = build_stream_upload(state.stream_df)
            uploads = [stream_upload] + uploads
    except Exception:
        # be defensive: if conversion fails, just return uploads
        pass
    return jsonify({"uploads": uploads})


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


@app.route('/api/instrument/add', methods=['POST'])
def api_instrument_add(): 
    j = request.get_json() or {}
    typ = j.get('type')
    if typ == 'keithley2602' or typ == 'keithley':
        k = Keithley2602()
        iid = f'keithley2602_{len(state.instruments)+1}'
        state.instruments[iid] = {'obj': k}
        return jsonify({'ok': True, 'id': iid, 'type': 'keithley2602'})
    if typ == 'keithley6430' or typ == '6430':
        k = Keithley6430()
        iid = f'keithley6430_{len(state.instruments)+1}'
        state.instruments[iid] = {'obj': k}
        return jsonify({'ok': True, 'id': iid, 'type': 'keithley6430'})
    if typ == 'notes':
        k = NotesInstrument()
        iid = f'notes_{len(state.instruments)+1}'
        state.instruments[iid] = {'obj': k}
        return jsonify({'ok': True, 'id': iid, 'type': 'notes'})
    return jsonify({'error': 'unknown type'}), 400


@app.route('/api/instruments', methods=['GET'])
def api_instruments_list():
    out = []
    for iid, entry in state.instruments.items():
        inst = entry.get('obj')
        tname = getattr(inst, '__class__', type(inst)).__name__
        out.append({'id': iid, 'type': tname})
    return jsonify({'instruments': out})


@app.route('/api/instrument/<iid>/card', methods=['GET'])
def api_instrument_card(iid):
    entry = state.instruments.get(iid)
    if not entry:
        return jsonify({'error': 'not found'}), 404
    inst = entry.get('obj') if isinstance(entry, dict) else entry
    tname = getattr(inst, '__class__', type(inst)).__name__
    try:
        html = inst.card_html(iid, type_name=tname)
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
        return jsonify({'ok': True, 'status': inst.status, 'idn': getattr(inst, 'idn', None)})
    else:
        return jsonify({'ok': False, 'status': inst.status}), 500


@app.route('/api/instrument/<iid>/close', methods=['POST'])
def api_instrument_close(iid):
    entry = state.instruments.get(iid)
    if not entry:
        return jsonify({'error': 'not found', 'status':'404'}), 404
    inst = entry['obj'] if isinstance(entry, dict) else entry
    try:
        inst.close()
    except Exception as e:
        return jsonify({'error': str(e), 'status':inst.status}), 500
    return jsonify({'ok': True, 'status':inst.status})


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
    state.instruments.pop(iid)
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
        print(f'ERROR: In trying to update instrument {iid}, got', e)
        return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    load_state_from_disk()
    app.run(host="0.0.0.0", port=5000, debug=True)

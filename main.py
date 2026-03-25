
import os
import threading
import io
import csv
from datetime import datetime
import json
from flask import Flask, render_template, jsonify, request
try:
    import pyvisa
except Exception:
    pyvisa = None

app = Flask(__name__, static_folder="static", template_folder="templates")


# Shared state for instrument connection and uploads
class InstrumentState:
    def __init__(self):
        self.rm = None
        self.inst = None
        self.status = "not opened"
        self.idn = None
        self.upload = None
        self.uploads = []
        self._next_upload_id = 1

    def new_upload_id(self):
        uid = self._next_upload_id
        self._next_upload_id += 1
        return uid


state = InstrumentState()
# load_state_from_disk()


def open_instrument(address=None, timeout=5):
    """Attempt to open a connection to a Keithley 2602.

    If `address` is provided it will be used. Otherwise we scan available
    resources, query *IDN? and pick the device that identifies as a 2602.
    """
    if pyvisa is None:
        state.status = "pyvisa not installed"
        return

    try:
        state.rm = pyvisa.ResourceManager()
    except Exception as e:
        state.status = f"failed to create ResourceManager: {e}"
        return

    resources = []
    try:
        resources = list(state.rm.list_resources())
    except Exception as e:
        state.status = f"failed to list resources: {e}"
        return

    # If explicit address given, try that first
    try_order = []
    if address:
        try_order.append(address)
    try_order.extend(r for r in resources if r not in try_order)

    for res in try_order:
        try:
            inst = state.rm.open_resource(res, timeout=timeout * 1000)
            try:
                idn = inst.query("*IDN?").strip()
            except Exception:
                idn = None

            if idn and "2602" in idn:
                state.inst = inst
                state.status = "opened"
                state.idn = idn
                return
            else:
                try:
                    inst.close()
                except Exception:
                    pass
        except Exception:
            continue

    state.status = "no Keithley 2602 found"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status", methods=["GET"])
def api_status():
    # Attempt a quick connection check on demand
    if state.status != "opened":
        address = os.environ.get("KEITHLEY_ADDRESS")
        open_instrument(address=address)
    return jsonify({"status": state.status, "idn": state.idn})


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

    return {"headers": headers, "columns": columns, "rows_count": len(rows)}


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
    data = {"uploads": state.uploads, "next_upload_id": state._next_upload_id}
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


def start_connection_background():
    address = os.environ.get("KEITHLEY_ADDRESS")
    open_instrument(address=address)


if __name__ == "__main__":
    t = threading.Thread(target=start_connection_background, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=True)


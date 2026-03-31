from InstrumentBase import InstrumentBase
from Sweep import Sweep
import threading
import queue as pyqueue

try:
    import pyvisa
except Exception:
    pyvisa = None


class Keithley6430(InstrumentBase):
    """Keithley 6430 driver using SCPI commands.

    This class intentionally keeps the same flat-key settings shape used by the
    existing frontend while translating those settings to SCPI.
    """
    DEFAULT_SETTINGS = {
        "output": False,
        "nplc": 1,
        "source": "voltage",
        "src_voltage_range": 0.2,
        "src_voltage_limit": 0.2,
        "src_current_range": 1e-12,
        "src_current_limit": 1e-12,
        "meas_voltage_range": 2,
        "meas_current_range": 1e-12
    }
    ADDRESSES_IN_USE:list[str] = []

    def __init__(self):
        super().__init__()
        self.rm = None
        self.idn = '-'
        self.sweep = Sweep([0])
        self._sweep_idx = 0
        self._io_queue = pyqueue.Queue()
        self._io_thread = None
        self._io_stop = threading.Event()
    def _start_io_worker(self):
        if self._io_thread is not None and self._io_thread.is_alive():
            return
        self._io_stop.clear()
        self._io_thread = threading.Thread(target=self._io_worker, daemon=True)
        self._io_thread.start()
    def _stop_io_worker(self):
        t = self._io_thread
        if t is None:
            return
        self._io_stop.set()
        self._io_queue.put(None)
        t.join(timeout=2)
        self._io_thread = None
    def _io_worker(self):
        while not self._io_stop.is_set():
            item = self._io_queue.get()
            if item is None:
                self._io_queue.task_done()
                break

            op, cmd, output_type, box, done = item
            try:
                if self.inst is None:
                    raise RuntimeError('Instrument not open')

                if op == 'write':
                    self.inst.write(cmd)
                    # Optionally check instrument error queue in-band with command order.
                    try:
                        err = self.inst.query(':SYST:ERR?').strip()
                        if 'no error' not in err.lower():
                            print(f'{err} (from {cmd})')
                    except Exception:
                        pass
                    box['result'] = None
                elif op == 'query':
                    raw = self.inst.query(cmd).strip()
                    box['result'] = output_type(raw)
                else:
                    raise ValueError(f'Unknown queued op: {op}')
            except Exception as e:
                box['error'] = e
            finally:
                done.set()
                self._io_queue.task_done()
    def _enqueue_io(self, op: str, cmd: str, output_type=str):
        if self.inst is None:
            raise RuntimeError('Instrument not open')
        self._start_io_worker()
        box = {}
        done = threading.Event()
        self._io_queue.put((op, cmd, output_type, box, done))
        done.wait()
        if 'error' in box:
            raise box['error']
        return box.get('result')
    def _parse_eng_value(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)

        s = str(value).strip()
        if not s:
            return None
        if s.startswith("+-"):
            s = s[2:]
        if s.startswith("±"):
            s = s[1:]
        s = s.replace("A", "").replace("V", "").strip()

        scale = 1.0
        if s.endswith("p"):
            scale = 1e-12
            s = s[:-1]
        elif s.endswith("n"):
            scale = 1e-9
            s = s[:-1]
        elif s.endswith("u"):
            scale = 1e-6
            s = s[:-1]
        elif s.endswith("m"):
            scale = 1e-3
            s = s[:-1]

        return float(s) * scale
    def open(self, address=None, timeout=5):
        if pyvisa is None:
            raise RuntimeError("pyvisa not available")

        self.rm = pyvisa.ResourceManager()
        resources = list(self.rm.list_resources())
        try_order = []
        if address:
            try_order.append(address)
        try_order.extend(r for r in resources if r not in try_order if "GPIB" in r)
        try_order.extend(r for r in resources if r not in try_order)

        for addr in try_order:
            try:
                inst = self.rm.open_resource(addr, timeout=timeout * 1000)
                inst.write_termination = "\n"
                inst.read_termination = "\n"
                idn = inst.query("*IDN?").strip()
                if "6430" in idn:
                    self.inst = inst
                    self.idn = idn
                    self._start_io_worker()
                    # Baseline SCPI setup for deterministic reads.
                    self.write("*CLS")
                    self.write("*RST")
                    self.write(":FORM:ELEM VOLT,CURR")
                    self.update(self.settings)
                    self.status = 'open'
                    self.__class__.ADDRESSES_IN_USE.append(addr)
                    return True
                try:
                    inst.close()
                except Exception:
                    pass
            except Exception as e:
                print(f"ERROR: While trying to open instrument at address {addr}, got exception", e)

        return False
    def close(self):
        if self.inst is None:
            return
        addr = self.inst.resource_name
        self._stop_io_worker()
        res = super().close()
        cls = self.__class__
        if addr in cls.ADDRESSES_IN_USE:
            cls.ADDRESSES_IN_USE.pop(cls.ADDRESSES_IN_USE.index(addr))
        return res
    def write(self, cmd:str):
        self._enqueue_io('write', cmd)
    def query(self, q:str, output_type=str):
        return self._enqueue_io('query', q, output_type)
    def update(self, settings: dict):
        allowed_keys = (
            "output",
            "nplc",
            "source",
            "src_voltage_range",
            "src_voltage_limit",
            "src_current_range",
            "src_current_limit",
            "meas_voltage_range",
            "meas_current_range"
        )
        if 'level' in settings:
            try:
                self.sweep = Sweep.from_string(settings.pop('level'))
            except:
                self.sweep = Sweep([0])

        for k in settings.keys():
            if k not in allowed_keys:
                raise ValueError(f"Unsupported setting key: {k}")

        self.settings.update(settings)
        if self.inst is None:
            return True

        source = self.get("source").lower()
        out_flag = bool(self.get("output"))

        try:
            if source == "voltage":
                self.write(":source:function voltage")
                self.write(":source:voltage:mode fixed")
                self.write(":sense:function \"current\"")
            else:
                self.write(":source:function current")
                self.write(":source:current:mode fixed")
                self.write(":sense:function \"voltage\"")
        except Exception as e:
            print("ERROR: While trying to set source function", e)

        try:
            nplc = int(float(self.get("nplc")))
            nplc = max(1, min(10, nplc))
            self.write(f":sense:current:NPLC {nplc}")
            self.write(f":sense:voltage:NPLC {nplc}")
        except Exception as e:
            print("ERROR: While trying to set NPLC", e)

        try:
            meas_vrange = self._parse_eng_value(self.get("meas_voltage_range"))
            meas_irange = self._parse_eng_value(self.get("meas_current_range"))
            if meas_vrange and source != 'voltage':
                self.write(f":sense:voltage:range {meas_vrange:.6e}")
            if meas_irange and source != 'current':
                self.write(f":sense:current:range {meas_irange:.6e}")

            # Compliance maps to opposite domain protection in SCPI.
            v_prot = self._parse_eng_value(self.get("src_voltage_limit"))
            i_prot = self._parse_eng_value(self.get("src_current_limit"))
            if v_prot is not None and source != 'voltage':
                self.write(f":sense:voltage:protection {v_prot:.6e}")
            if i_prot is not None and source != 'current':
                self.write(f":sense:current:protection {i_prot:.6e}")
        except Exception as e:
            print("ERROR: While trying to set compliance", e)

        try:
            src_vrange = self._parse_eng_value(self.get("src_voltage_range"))
            src_irange = self._parse_eng_value(self.get("src_current_range"))

            if src_vrange:
                self.write(f":source:voltage:range {src_vrange:.6e}")
            if src_irange:
                self.write(f":source:current:range {src_irange:.6e}")
        except Exception as e:
            print("ERROR: While trying to set ranges", e)

        try:
            self.write(f":OUTP {'ON' if out_flag else 'OFF'}")
        except Exception as e:
            print("ERROR: While trying to set output", e)

        return True
    def measure(self):
        out = {"v": None, "i": None}
        if self.inst is None:
            return out

        try:
            # self.write(":FORM:ELEM VOLT,CURR")
            raw = self.query(":read?")
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if len(parts) >= 1:
                out["v"] = float(parts[0])
            if len(parts) >= 2:
                out["i"] = float(parts[1])
        except Exception as e:
            print("ERROR: While trying to measure from 6430", e)

        source = self.get("source").lower()
        if source == "voltage":
            out["setv"] = self.query('source:voltage:level?')
        else:
            out["seti"] = self.query('source:current:level?')

        return out
    def start(self):
        # Present for compatibility with the shared measurement thread API.
        self._sweep_idx = 0
    def next(self):
        # Keep source level applied from settings before each reading.
        if self.inst is not None and bool(self.get("output")):
            src = self.get("source")
            val = self.sweep[self._sweep_idx]
            if src == "voltage":
                self.write(f":source:voltage:level {val:.6e}")
            else:
                self.write(f":source:current:level {val:.6e}")
            self._sweep_idx += 1

        return self.measure()
    def card_html(self, iid: str, type_name: str = "keithley6430") -> str:
        checked = " checked" if bool(self.get("output")) else ""
        source = str(self.get("source") or "current")
        nplc_now = self.get("nplc")
        nplc_options = "".join(
            [f'<option value="{i}"{" selected" if str(nplc_now) == str(i) else ""}>{i}</option>' for i in range(1, 11)]
        )

        volt_opts = ["±200mV", "±2V", "±20V"]
        curr_opts = ["±1pA", "±10pA", "±100pA", "±1nA", "±10nA", "±100nA", "±1uA", "±10uA", "±100uA", "±1mA", "±10mA"]

        def _opts(options_list, current):
            cur = str(current)
            return "".join([f'<option value="{o}"{" selected" if cur == str(o) else ""}>{o}</option>' for o in options_list])

        src_v_limit = self.get("src_voltage_limit")
        src_i_limit = self.get("src_current_limit")

        return f"""
    <h3>{type_name} <small>({iid})</small></h3>
    <p>Status: <span class=\"status\">{self.status}</span></p>
    <p>IDN: <span class=\"idn\">{self.idn}</span></p>
    <div class=\"device-controls\">
        <button class=\"open\">Open</button>
        <button class=\"close\">Close</button>
        <button class=\"remove\">Remove</button>
    </div>
    <div class=\"grid\">
        <div class=\"col\" id=\"{iid}-sourcing\">
            <h4>General Setup</h4>
            <label>Output: <input type=\"checkbox\" data-key=\"output\"{checked} /></label>
            <label>NPLC: <select data-key=\"nplc\">{nplc_options}</select></label>
            <label>Source: <select data-key=\"source\"><option value=\"current\"{' selected' if source == 'current' else ''}>Current</option><option value=\"voltage\"{' selected' if source == 'voltage' else ''}>Voltage</option></select></label>
            <label>Level: <input type=\"text\" data-key=\"level\" value=\"{str(self.sweep)[1:-1]}\"/></label>
        </div>
        <div class=\"col\" id=\"{iid}-sourcing-voltage\">
            <h4>Sourcing Voltage</h4>
            <label>Source Range: <select data-key=\"src_voltage_range\">{_opts(volt_opts, self.get('src_voltage_range'))}</select></label>
            <label>Compliance (A): <input type=\"number\" step=\"any\" data-key=\"src_current_limit\" value=\"{'' if src_i_limit is None else src_i_limit}\"/></label>
            <label>Sense Range: <select data-key=\"meas_current_range\">{_opts(curr_opts, self.get('meas_current_range'))}</select></label>
            <p>Compliance must be larger than sense range.</p>
        </div>
        <div class=\"col\" id=\"{iid}-sourcing-current\">
            <h4>Sourcing Current</h4>
            <label>Source Range: <select data-key=\"src_current_range\">{_opts(curr_opts, self.get('src_current_range'))}</select></label>
            <label>Compliance (V): <input type=\"number\" step=\"any\" data-key=\"src_voltage_limit\" value=\"{'' if src_v_limit is None else src_v_limit}\"/></label>
            <label>Sense Range: <select data-key=\"meas_voltage_range\">{_opts(volt_opts, self.get('meas_voltage_range'))}</select></label>
        </div>
        </div>
    """

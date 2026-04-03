from InstrumentBase import PyVisaInstrument
from Sweep import Sweep


class Keithley6430(PyVisaInstrument):
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

    def __init__(self):
        super().__init__()
        self.sweep = Sweep([0])
        self._sweep_idx = 0
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
    def _check_for_errors(self, prev_cmd):
        err = self.query(':SYST:ERR?', check_for_errors=False)
        if 'no error' not in err.lower():
            print(f'ERROR in Keithley6430: {err} (from {prev_cmd})')
    def _find(self, address:str=None, timeout:float=5):
        return super()._find(address=address, timeout=timeout, query='*IDN?', look_for='KEITHLEY INSTRUMENTS INC.,MODEL 6430')
    def _initialize(self):
        # Baseline SCPI setup for deterministic reads.
        self.write("*CLS")
        self.write("*RST")
        self.write('SYST:TIME:RES')
        # self.write('FORM:DATA SRE')
        # self.write('SOUR:FUNC VOLT')
        # self.write('SOUR:VOLT 0.00')
        self.write('SENS:FUNC:ON "VOLT", "CURR"')
        self.write('SENS:FUNC:OFF "RES"')
        # self.write('CURR:PROT:LEV 1.0E-1')
        # self.write('SENS:CURR:RANG 1.0E-6')
        # self.write('SENS:RES:NPLC 10')
        self.write('AVER OFF')
        # self.write('DISP:DIG 4')
        # self.write('OUTP ON')
        self.write(":FORM:ELEM VOLT,CURR")
        # self.write(':SOUR:DEL:AUTO ON')
        # self.write(':SENSe:AVERage:AUTO ON')
        self.update(self.settings, force=True)
        return True
    def update(self, settings: dict, force:bool=False):
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
                self.sweep = Sweep.from_string(settings.pop('level'), float)
            except:
                return False

        for k in settings.keys():
            if k not in allowed_keys:
                raise ValueError(f"Unsupported setting key: {k}")

        old_settings = self.settings.copy()
        self.settings.update(settings)

        changed_keys = {k for k, v in settings.items() if old_settings.get(k) != v or force}
        source_changed = 'source' in changed_keys

        # If nothing changed, skip instrument communication entirely.
        if not changed_keys:
            return True

        if self.inst is None:
            return True

        source = self.get("source").lower()
        out_flag = bool(self.get("output"))

        try:
            if source_changed:
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
            if 'nplc' in changed_keys:
                nplc = int(float(self.get("nplc")))
                nplc = max(1, min(10, nplc))
                self.write(f":sense:current:NPLCycles {nplc}")
                self.write(f":sense:voltage:NPLCycles {nplc}")
        except Exception as e:
            print("ERROR: While trying to set NPLC", e)

        try:
            meas_vrange = self._parse_eng_value(self.get("meas_voltage_range"))
            meas_irange = self._parse_eng_value(self.get("meas_current_range"))
            if (source_changed or 'meas_voltage_range' in changed_keys) and meas_vrange and source != 'voltage':
                self.write(f":sense:voltage:range {meas_vrange:.6e}")
            if (source_changed or 'meas_current_range' in changed_keys) and meas_irange and source != 'current':
                self.write(f":sense:current:range {meas_irange:.6e}")

            # Compliance maps to opposite domain protection in SCPI.
            v_prot = self._parse_eng_value(self.get("src_voltage_limit"))
            i_prot = self._parse_eng_value(self.get("src_current_limit"))
            if (source_changed or 'src_voltage_limit' in changed_keys) and v_prot is not None and source != 'voltage':
                self.write(f":sense:voltage:protection {v_prot:.6e}")
            if (source_changed or 'src_current_limit' in changed_keys) and i_prot is not None and source != 'current':
                self.write(f":sense:current:protection {i_prot:.6e}")
        except Exception as e:
            print("ERROR: While trying to set compliance", e)

        try:
            src_vrange = self._parse_eng_value(self.get("src_voltage_range"))
            src_irange = self._parse_eng_value(self.get("src_current_range"))

            if (source_changed or 'src_voltage_range' in changed_keys) and src_vrange:
                self.write(f":source:voltage:range {src_vrange:.6e}")
            if (source_changed or 'src_current_range' in changed_keys) and src_irange:
                self.write(f":source:current:range {src_irange:.6e}")
        except Exception as e:
            print("ERROR: While trying to set ranges", e)

        try:
            if 'output' in changed_keys:
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
                if out["v"] > 9.9e37:
                    out["v"] = None
            if len(parts) >= 2:
                out["i"] = float(parts[1])
                if out["i"] > 9.9e37:
                    out["i"] = None
        except Exception as e:
            print("ERROR: While trying to measure from 6430", e)

        source = self.get("source").lower()
        if source == "voltage":
            out["setv"] = self.query('source:voltage:level?', float)
            if out["setv"] > 9.9e37:
                out["setv"] = None
        else:
            out["seti"] = self.query('source:current:level?', float)
            if out["seti"] > 9.9e37:
                out["seti"] = None

        return out
    def start(self):
        # Present for compatibility with the shared measurement thread API.
        self._sweep_idx = 0
    def next(self):
        # Keep source level applied from settings before each reading.
        if self.inst is not None and bool(self.get("output")):
            src = self.get("source")
            val = self.sweep[self._sweep_idx] # this will raise a StopSweep exception when it finishes
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

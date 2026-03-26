import time
from abc import ABC, abstractmethod
try:
    import pyvisa
except Exception:
    pyvisa = None


class InstrumentBase(ABC):
    """Abstract base class for instruments used by the GUI.

    Subclasses should implement low-level operations the server expects:
    - `open(address, timeout)`
    - `close()`
    - `write(cmd)` and `query(q)` for instrument I/O
    - `apply_smu(which, cfg)` (optional)
    - `measure()` returning a dict of measurements
    - `update(settings)` to accept generic per-device updates
    """

    @abstractmethod
    def open(self, address=None, timeout=5):
        raise NotImplementedError()

    @abstractmethod
    def close(self):
        raise NotImplementedError()

    @abstractmethod
    def write(self, cmd):
        raise NotImplementedError()

    @abstractmethod
    def query(self, q):
        raise NotImplementedError()

    def apply_smu(self, which, smu):
        """Optional: apply SMU settings for channel `which`.

        Implementations may provide this; default is to raise NotImplementedError
        so callers can fall back if needed.
        """
        raise NotImplementedError()

    @abstractmethod
    def measure(self):
        raise NotImplementedError()

    def update(self, settings: dict):
        """Optional: accept a generic settings dict and apply them.

        This allows the server to send device-specific payloads
        (for example {'a': {...}, 'b': {...}} for a Keithley 2602).
        Implementations should return a dict or True/False.
        """
        raise NotImplementedError()

    @abstractmethod
    def card_html(self, iid: str, type_name: str = None) -> str:
        """Return an HTML string for the device card shown on /connect.

        Subclasses should produce a small block of HTML to be injected into
        the devices container. `iid` is the instrument id assigned by the
        server and `type_name` is an optional human-readable device type.
        """
        raise NotImplementedError()


class Keithley2602(InstrumentBase):
    """Minimal wrapper for a Keithley 2602 instrument.

    Provides `open(address)`, `close()`, `apply_smu(which, cfg)`, `update(settings)`
    and `measure()`.
    """
    DEFAULT_SETTINGS = {
                "output": False,
                "nplc": 1,
                "source": "voltage",
                "src_voltage_range": "±100mV",
                "src_voltage_limit": 0.0,
                "src_current_range": "±100nA",
                "src_current_limit": 0.0,
                "meas_voltage_range": "±100mV",
                "meas_current_range": "±100nA"
            }

    def __init__(self):
        self.rm = None
        self.inst = None
        self.idn = None
        # SMU configs for A and B
        self.settings = {'a' : Keithley2602.DEFAULT_SETTINGS.copy(),
                         'b' : Keithley2602.DEFAULT_SETTINGS.copy() }

    def open(self, address=None, timeout=5):
        if pyvisa is None:
            raise RuntimeError('pyvisa not available')
        self.rm = pyvisa.ResourceManager()
        resources = list(self.rm.list_resources())
        try_order = []
        if address:
            try_order.append(address)
        try_order.extend(r for r in resources if r not in try_order)
        for res in try_order:
            try:
                inst = self.rm.open_resource(res, timeout=timeout * 1000)
                try:
                    idn = inst.query('*IDN?').strip()
                except Exception:
                    idn = None
                if idn and '2602' in idn:
                    self.inst = inst
                    self.idn = idn
                    return True
                else:
                    try:
                        inst.close()
                    except Exception:
                        pass
            except Exception:
                continue
        return False

    def close(self):
        if self.inst is not None:
            try:
                self.inst.close()
            except Exception:
                pass
            self.inst = None

    def write(self, cmd):
        if self.inst is None:
            raise RuntimeError('instrument not open')
        self.inst.write(cmd)

    def query(self, q):
        if self.inst is None:
            raise RuntimeError('instrument not open')
        return self.inst.query(q)

    def update(self, settings:dict):
        """Apply configuration SMU A and/or B. Best-effort.
        Settings is a dictionary with entries
            "a": {  "output": False,
                    "nplc": 1,
                    "source": "voltage",
                    "src_voltage_range": "±100mV",
                    "src_voltage_limit": 0.0,
                    "src_current_range": "±100nA",
                    "src_current_limit": 0.0,
                    "meas_voltage_range": "±100mV",
                    "meas_current_range": "±100nA"
                },
            "b": ...

            Unspecified entries will not be set.
        """

        try:
            for smu, smu_settings in settings.items():
                if len([k for k in smu_settings if k not in self.settings]) != 0:
                    raise ValueError(f'Settings has disallowed keys: {list([k for k in smu_settings if k not in self.settings])}')

                if smu != 'a' and smu != 'b':
                    raise ValueError(f'2602 only has smu a and b, but you provided {smu}!')

                self.settings[smu].update(smu_settings)
                if not self.settings.get('output'): # turn output off first if that is what is desired. Otherwise leave it alone.
                    self.inst.write(f"smu{smu}.source.output = smu{smu}.OUTPUT_OFF")

                if self.settings.get('source', self.DEFAULT_SETTINGS['source']) == 'voltage':
                    self.inst.write(f"smu{smu}.source.func = smu{smu}.OUTPUT_DCVOLTS")
                    self.inst.write(f"smu{smu}.source.levelv = 0")
                    self.inst.write(f"display.smu{smu}.measure.func = display.MEASURE_DCAMPS")
                else:
                    self.inst.write(f"smu{smu}.source.func = smu{smu}.OUTPUT_DCCURRENT")
                    self.inst.write(f"smu{smu}.source.leveli = 0")
                    self.inst.write(f"display.smu{smu}.measure.func = display.MEASURE_DCVOLTS")

                if 'nplc' in smu:
                    self.inst.write(f"smu{smu}.measure.nplc = {int(self.settings.get('nplc', self.DEFAULT_SETTINGS['nplc']))}")

                # ranges / limits if provided
                if 'src_voltage_limit' in smu:
                    self.inst.write(f"smu{smu}.source.limitv = {float(self.settings.get('src_voltage_limit', self.DEFAULT_SETTINGS['src_voltage_limit'])):.6e}")
                if 'src_current_limit' in smu:
                    self.inst.write(f"smu{smu}.source.limiti = {float(self.settings.get('src_current_limit', self.DEFAULT_SETTINGS['src_current_limit'])):.6e}")

                if self.settings.get('output'):
                    self.inst.write(f"smu{smu}.source.output = smu{smu}.OUTPUT_ON")
                else:
                    self.inst.write(f"smu{smu}.source.output = smu{smu}.OUTPUT_OFF")

            return True
        except Exception:
            return False

    def measure(self):
        """Return a flat dictionary of measurements.

        Format: {'2602a voltage': val_or_none, 
                 '2602a current': ..., 
                 '2602b voltage': ...,
                 '2602b current': ...}
        """
        out = {'2602a voltage': None, '2602a current': None, '2602b voltage': None, '2602b current': None}
        if self.inst is None:
            return out
        for k in ('a', 'b'):
            try:
                v = self.inst.query(f'print(smu{k}.measure.v())').strip()
                i = self.inst.query(f'print(smu{k}.measure.i())').strip()
                out[f'2602{k} voltage'] = float(v)
                out[f'2602{k} current'] = float(i)
            except Exception:
                pass
        return out

    def card_html(self, iid: str, type_name: str = 'keithley2602') -> str:
            """Return HTML markup for a Keithley 2602 device card, including SMU controls.

            This mirrors the structure expected by the client-side `connect.js`.
            """
            # Use the same class names as the client so CSS and JS wiring works
            return f"""
        <h3>{type_name} <small>({iid})</small></h3>
        <p>Status: <span class=\"status\">closed</span> IDN: <span class=\"idn\">-</span></p>
        <div class=\"device-controls\">
            <button class=\"open\">Open</button>
            <button class=\"close\">Close</button>
            <button class=\"force\">Force Update</button>
            <button class=\"remove\">Remove</button>
        </div>
        <div class=\"smu-grid\">
            <div class=\"smu-col\" id=\"{iid}-smu-A\">
                <h4>SMU A</h4>
                <label>Output: <input type=\"checkbox\" id=\"{iid}-smuA-output\" /></label>
                <label>NPLC: <select id=\"{iid}-smuA-nplc\"></select></label>
                <label>Source: <select id=\"{iid}-smuA-source\"><option value=\"voltage\">Voltage</option><option value=\"current\">Current</option></select></label>
                <label>Source Voltage Range: <select id=\"{iid}-smuA-src-voltage-range\"></select></label>
                <label>Source Voltage Limit: <input id=\"{iid}-smuA-src-voltage-limit\" type=\"number\" step=\"any\"/></label>
                <label>Source Current Range: <select id=\"{iid}-smuA-src-current-range\"></select></label>
                <label>Source Current Limit: <input id=\"{iid}-smuA-src-current-limit\" type=\"number\" step=\"any\"/></label>
                <label>Measure Voltage Range: <select id=\"{iid}-smuA-meas-voltage-range\"></select></label>
                <label>Measure Current Range: <select id=\"{iid}-smuA-meas-current-range\"></select></label>
            </div>
            <div class=\"smu-col\" id=\"{iid}-smu-B\">
                <h4>SMU B</h4>
                <label>Output: <input type=\"checkbox\" id=\"{iid}-smuB-output\" /></label>
                <label>NPLC: <select id=\"{iid}-smuB-nplc\"></select></label>
                <label>Source: <select id=\"{iid}-smuB-source\"><option value=\"voltage\">Voltage</option><option value=\"current\">Current</option></select></label>
                <label>Source Voltage Range: <select id=\"{iid}-smuB-src-voltage-range\"></select></label>
                <label>Source Voltage Limit: <input id=\"{iid}-smuB-src-voltage-limit\" type=\"number\" step=\"any\"/></label>
                <label>Source Current Range: <select id=\"{iid}-smuB-src-current-range\"></select></label>
                <label>Source Current Limit: <input id=\"{iid}-smuB-src-current-limit\" type=\"number\" step=\"any\"/></label>
                <label>Measure Voltage Range: <select id=\"{iid}-smuB-meas-voltage-range\"></select></label>
                <label>Measure Current Range: <select id=\"{iid}-smuB-meas-current-range\"></select></label>
            </div>
        </div>
        <div class=\"device-plot\" style=\"height:240px\"></div>
            """

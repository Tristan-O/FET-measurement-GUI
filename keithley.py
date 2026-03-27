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
        "smua.output": False,
        "smua.nplc": 1,
        "smua.source": "voltage",
        "smua.src_voltage_range": "±100mV",
        "smua.src_voltage_limit": 0.1,
        "smua.src_current_range": "±100nA",
        "smua.src_current_limit": 1e-7,
        "smua.meas_voltage_range": "±100mV",
        "smua.meas_current_range": "±100nA",

        "smub.output": False,
        "smub.nplc": 1,
        "smub.source": "voltage",
        "smub.src_voltage_range": "±100mV",
        "smub.src_voltage_limit": 0.1,
        "smub.src_current_range": "±100nA",
        "smub.src_current_limit": 1e-7,
        "smub.meas_voltage_range": "±100mV",
        "smub.meas_current_range": "±100nA"
    }

    def __init__(self):
        self.rm = None
        self.inst = None
        self.idn = None
        # flat SMU configuration dictionary with keys like 'smua.output', 'smub.nplc'
        self.settings = Keithley2602.DEFAULT_SETTINGS.copy()

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
                    # apply stored settings to the opened instrument
                    self.update(self.settings)
                    return True
                else:
                    try:
                        inst.close()
                    except Exception:
                        pass
            except Exception as e:
                print(e)
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

    def update(self, settings: dict):
        """Apply configuration using flat keys like 'smua.output' and 'smub.nplc'.

        This method validates the provided keys, merges them into the stored
        `self.settings` dict, and if the instrument is open, issues the
        appropriate TSP commands to apply the configuration.
        """
        allowed_fields = (
            'output', 'nplc', 'source', 'src_voltage_range', 'src_voltage_limit',
            'src_current_range', 'src_current_limit', 'meas_voltage_range', 'meas_current_range'
        )
        allowed_keys = [f'smua.{f}' for f in allowed_fields] + [f'smub.{f}' for f in allowed_fields]

        for k in settings.keys():
            if k not in allowed_keys:
                raise ValueError(f'Unsupported setting key: {k}')
        
        # merge into stored settings
        self.settings.update(settings)
        for k,v in self.settings.items():
            if isinstance(v, str) and v.startswith('±'):
                self.settings[k] = float(v[1:-1].replace('m', 'e-3').replace('u', 'e-6').replace('n', 'e-9'))


        # if instrument not open, nothing more to do
        if self.inst is None:
            return True

        # apply settings to the instrument
        def get(smux, key):
            return self.settings.get(f'{smux}.{key}', Keithley2602.DEFAULT_SETTINGS.get(f'{smux}.{key}'))
        def write(cmd):
            print(cmd)
            self.inst.write(cmd)
            
        for smux in ('smua', 'smub'):
            out_flag = get(smux, 'output')

            # ensure output off while configuring
            if not out_flag:
                try:
                    write(f"{smux}.source.output = {smux}.OUTPUT_OFF")
                except Exception as e:
                    print('ERROR: While trying to set output state',e)

            source = get(smux, 'source')
            try:
                if source == 'voltage':
                    write(f"{smux}.source.func = {smux}.OUTPUT_DCVOLTS")
                    write(f"{smux}.source.levelv = 0")
                    write(f"display.{smux}.measure.func = display.MEASURE_DCAMPS")
                else:
                    write(f"{smux}.source.func = {smux}.OUTPUT_DCCURRENT")
                    write(f"{smux}.source.leveli = 0")
                    write(f"display.{smux}.measure.func = display.MEASURE_DCVOLTS")
            except Exception as e:
                print('ERROR: While trying to set output type (V, I)',e)

            try:
                nplc = int(get(smux, 'nplc'))
                write(f"{smux}.measure.nplc = {nplc}")
            except Exception as e:
                print('ERROR: While trying to set NPLC',e)

            try:
                src_vrange = float(get(smux, 'src_voltage_range'))
                mes_vrange = float(get(smux, 'src_voltage_range'))
                vlim = float(get(smux, 'src_voltage_limit')) or float(Keithley2602.DEFAULT_SETTINGS.get(f'{smux}.src_voltage_limit'))
                write(f"{smux}.source.rangev = {src_vrange:0.6e}")
                write(f"{smux}.measure.rangev = {mes_vrange:0.6e}")
                write(f"{smux}.source.limitv = {vlim:.6e}")
            except Exception as e:
                print('ERROR: While trying to set voltage range/limit',e)

            try:
                src_irange = float(get(smux, 'src_current_range'))
                mes_irange = float(get(smux, 'src_current_range'))
                ilim = float(get(smux, 'src_current_limit')) or float(Keithley2602.DEFAULT_SETTINGS.get(f'{smux}.src_current_limit'))
                write(f"{smux}.source.rangei = {src_irange:0.6e}")
                write(f"{smux}.measure.rangei = {mes_irange:0.6e}")
                write(f"{smux}.source.limiti = {ilim:.6e}")
            except Exception as e:
                print('ERROR: While trying to set current range/limit',e)

            # apply output on/off after configuration
            try:
                if out_flag:
                    write(f"{smux}.source.output = {smux}.OUTPUT_ON")
                else:
                    write(f"{smux}.source.output = {smux}.OUTPUT_OFF")
            except Exception as e:
                print('ERROR: While trying to set output',e)

        return True

    def measure(self):
        """Return a flat dictionary of measurements.

        Format: {'A_v': val, 'A_i': val, 'B_v': val, 'B_i': val}
        """
        out = {'A_v': None, 'A_i': None, 'B_v': None, 'B_i': None}
        if self.inst is None:
            return out
        for k in ('a', 'b'):
            try:
                v = self.inst.query(f'print(smu{k}.measure.v())').strip()
                i = self.inst.query(f'print(smu{k}.measure.i())').strip()
                out[f'{k.upper()}_v'] = float(v)
                out[f'{k.upper()}_i'] = float(i)
            except Exception:
                pass
        return out

    def card_html(self, iid: str, type_name: str = 'keithley2602') -> str:
        """Return HTML markup for a Keithley 2602 device card, including SMU controls.

        Inputs/selects include `data-key` attributes mapping to flat setting keys
        (e.g. `smua.output`, `smub.nplc`). This allows the frontend to be
        instrument-agnostic and simply POST a flat dict of settings to the
        backend.
        """
        nplc_options = ''.join(f"<option value=\"{i}\">{i}</option>" for i in range(1, 11))
        volt_opts = ["±100mV", "±1V", "±6V", "±40V"]
        curr_opts = ["±100nA", "±1uA", "±10uA", "±100uA", "±1mA", "±10mA", "±100mA", "±1A"]
        volt_options = ''.join(f"<option value=\"{v}\">{v}</option>" for v in volt_opts)
        curr_options = ''.join(f"<option value=\"{c}\">{c}</option>" for c in curr_opts)

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
        <label>Output: <input type=\"checkbox\" id=\"{iid}-smuA-output\" data-key=\"smua.output\" /></label>
        <label>NPLC: <select id=\"{iid}-smuA-nplc\" data-key=\"smua.nplc\">{nplc_options}</select></label>
        <label>Source: <select id=\"{iid}-smuA-source\" data-key=\"smua.source\"><option value=\"voltage\">Voltage</option><option value=\"current\">Current</option></select></label>
        <label>Source Voltage Range: <select id=\"{iid}-smuA-src-voltage-range\" data-key=\"smua.src_voltage_range\">{volt_options}</select></label>
        <label>Source Voltage Limit: <input id=\"{iid}-smuA-src-voltage-limit\" type=\"number\" step=\"any\" data-key=\"smua.src_voltage_limit\"/></label>
        <label>Source Current Range: <select id=\"{iid}-smuA-src-current-range\" data-key=\"smua.src_current_range\">{curr_options}</select></label>
        <label>Source Current Limit: <input id=\"{iid}-smuA-src-current-limit\" type=\"number\" step=\"any\" data-key=\"smua.src_current_limit\"/></label>
        <label>Measure Voltage Range: <select id=\"{iid}-smuA-meas-voltage-range\" data-key=\"smua.meas_voltage_range\">{volt_options}</select></label>
        <label>Measure Current Range: <select id=\"{iid}-smuA-meas-current-range\" data-key=\"smua.meas_current_range\">{curr_options}</select></label>
      </div>
      <div class=\"smu-col\" id=\"{iid}-smu-B\">
        <h4>SMU B</h4>
        <label>Output: <input type=\"checkbox\" id=\"{iid}-smuB-output\" data-key=\"smub.output\" /></label>
        <label>NPLC: <select id=\"{iid}-smuB-nplc\" data-key=\"smub.nplc\">{nplc_options}</select></label>
        <label>Source: <select id=\"{iid}-smuB-source\" data-key=\"smub.source\"><option value=\"voltage\">Voltage</option><option value=\"current\">Current</option></select></label>
        <label>Source Voltage Range: <select id=\"{iid}-smuB-src-voltage-range\" data-key=\"smub.src_voltage_range\">{volt_options}</select></label>
        <label>Source Voltage Limit: <input id=\"{iid}-smuB-src-voltage-limit\" type=\"number\" step=\"any\" data-key=\"smub.src_voltage_limit\"/></label>
        <label>Source Current Range: <select id=\"{iid}-smuB-src-current-range\" data-key=\"smub.src_current_range\">{curr_options}</select></label>
        <label>Source Current Limit: <input id=\"{iid}-smuB-src-current-limit\" type=\"number\" step=\"any\" data-key=\"smub.src_current_limit\"/></label>
        <label>Measure Voltage Range: <select id=\"{iid}-smuB-meas-voltage-range\" data-key=\"smub.meas_voltage_range\">{volt_options}</select></label>
        <label>Measure Current Range: <select id=\"{iid}-smuB-meas-current-range\" data-key=\"smub.meas_current_range\">{curr_options}</select></label>
      </div>
    </div>
    <div class=\"device-plot\" style=\"height:240px\"></div>
    """

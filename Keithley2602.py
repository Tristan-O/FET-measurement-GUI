from InstrumentBase import InstrumentBase
from Sweep import Sweep
try:
    import pyvisa
except Exception:
    pyvisa = None


class Keithley2602(InstrumentBase):
    """Minimal wrapper for a Keithley 2602 instrument.

    Provides `open(address)`, `close()`, `update(settings)` and `measure()`.
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
        "smua.level": None,

        "smub.output": False,
        "smub.nplc": 1,
        "smub.source": "voltage",
        "smub.src_voltage_range": "±100mV",
        "smub.src_voltage_limit": 0.1,
        "smub.src_current_range": "±100nA",
        "smub.src_current_limit": 1e-7,
        "smub.meas_voltage_range": "±100mV",
        "smub.meas_current_range": "±100nA",
        "smub.level": None
    }

    def __init__(self):
        super().__init__()
        self.rm = None
        self.idn = None
        self.sweeps = [Sweep([0]), Sweep([0])] # A, B
        self._sweeps_iter = [None,None]
    def get(self, smux:str, key:str|None=None):
        '''Get a setting from the current settings dict.'''
        if key is not None:
            smux = f'{smux}.{key}'
        return super().get(smux)
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

        if 'smua.level' in settings:
            try:
                self.sweeps[0] = Sweep.from_string(settings.pop('smua.level'))
                self._sweeps_iter[0] = None
            except:
                pass
        if 'smub.level' in settings:
            try:
                self.sweeps[1] = Sweep.from_string(settings.pop('smub.level'))
                self._sweeps_iter[1] = None
            except:
                pass

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
            
        for smux in ('smua', 'smub'):
            out_flag = self.get(smux, 'output')

            # ensure output off while configuring
            if not out_flag:
                try:
                    self.write(f"{smux}.source.output = {smux}.OUTPUT_OFF")
                except Exception as e:
                    print('ERROR: While trying to set output state',e)

            source = self.get(smux, 'source')
            try:
                if source == 'voltage':
                    self.write(f"{smux}.source.func = {smux}.OUTPUT_DCVOLTS")
                    self.write(f"{smux}.source.levelv = 0")
                    self.write(f"display.{smux}.measure.func = display.MEASURE_DCAMPS")
                else:
                    self.write(f"{smux}.source.func = {smux}.OUTPUT_DCAMPS")
                    self.write(f"{smux}.source.leveli = 0")
                    self.write(f"display.{smux}.measure.func = display.MEASURE_DCVOLTS")
            except Exception as e:
                print('ERROR: While trying to set output type (V, I)',e)

            try:
                nplc = int(self.get(smux, 'nplc'))
                self.write(f"{smux}.measure.nplc = {nplc}")
            except Exception as e:
                print('ERROR: While trying to set NPLC',e)

            try:
                src_vrange = float(self.get(smux, 'src_voltage_range'))
                mes_vrange = float(self.get(smux, 'src_voltage_range'))
                vlim = float(self.get(smux, 'src_voltage_limit')) or float(Keithley2602.DEFAULT_SETTINGS.get(f'{smux}.src_voltage_limit'))
                self.write(f"{smux}.source.rangev = {src_vrange:0.6e}")
                self.write(f"{smux}.measure.rangev = {mes_vrange:0.6e}")
                self.write(f"{smux}.source.limitv = {vlim:.6e}")
            except Exception as e:
                print('ERROR: While trying to set voltage range/limit',e)

            try:
                src_irange = float(self.get(smux, 'src_current_range'))
                mes_irange = float(self.get(smux, 'src_current_range'))
                ilim = float(self.get(smux, 'src_current_limit')) or float(Keithley2602.DEFAULT_SETTINGS.get(f'{smux}.src_current_limit'))
                self.write(f"{smux}.source.rangei = {src_irange:0.6e}")
                self.write(f"{smux}.measure.rangei = {mes_irange:0.6e}")
                self.write(f"{smux}.source.limiti = {ilim:.6e}")
            except Exception as e:
                print('ERROR: While trying to set current range/limit',e)

            # apply output on/off after configuration
            try:
                if out_flag:
                    self.write(f"{smux}.source.output = {smux}.OUTPUT_ON")
                else:
                    self.write(f"{smux}.source.output = {smux}.OUTPUT_OFF")
            except Exception as e:
                print('ERROR: While trying to set output',e)

        return True
    def measure(self):
        """Return a flat dictionary of measurements.

        Format: {'smux.v': float, 'smux.i': float, 'smux.setv': float, 'smux.seti': float}
        """
        out = {'smua.v': None, 'smua.i': None, 'smua.setv': None, 'smua.seti': None,
               'smub.v': None, 'smub.i': None, 'smub.setv': None, 'smub.seti': None}
        if self.inst is None:
            return out

        def _get(cmd, key):
            try:
                out[key] = self.query(cmd, float)
            except:
                print(f'Unable to get {key} using command {cmd}')

        for smux in ('smua', 'smub'):
                _get(f'print({smux}.measure.v())', f'{smux}.v')
                _get(f'print({smux}.measure.i())', f'{smux}.i')
                _get(f'print({smux}.levelv)', f'{smux}.setv')
                _get(f'print({smux}.leveli)', f'{smux}.seti')
        return out
    def card_html(self, iid: str, type_name: str = 'keithley2602') -> str:
        """Return HTML markup for a Keithley 2602 device card, including SMU controls.

        Inputs/selects include `data-key` attributes mapping to flat setting keys
        (e.g. `smua.output`, `smub.nplc`). This allows the frontend to be
        instrument-agnostic and simply POST a flat dict of settings to the
        backend.
        """
        # Helper to parse range strings like "±100mV" -> numeric (in base units)
        def _parse_range_val(x):
            if x is None:
                return None
            if isinstance(x, (int, float)):
                return float(x)
            s = str(x).strip()
            # strip leading ± and trailing units
            if s.startswith('±'):
                s = s[1:]
            if s.endswith('V') or s.endswith('A'):
                unit = s[-1]
                s = s[:-1]
            # handle SI suffix
            mul = 1.0
            if s.endswith('n'):
                mul = 1e-9; s = s[:-1]
            elif s.endswith('u'):
                mul = 1e-6; s = s[:-1]
            elif s.endswith('m'):
                mul = 1e-3; s = s[:-1]
            try:
                return float(s) * mul
            except Exception:
                try:
                    return float(s)
                except Exception:
                    return None

        # option lists
        nplc_list = list(range(1, 11))
        volt_opts = ["±100mV", "±1V", "±6V", "±40V"]
        curr_opts = ["±100nA", "±1uA", "±10uA", "±100uA", "±1mA", "±10mA", "±100mA", "±1A"]

        def _opts_html_for_nplc(current):
            parts = []
            for i in nplc_list:
                sel = ' selected' if (str(current) == str(i) or (isinstance(current, (int,float)) and int(current) == i)) else ''
                parts.append(f'<option value="{i}"{sel}>{i}</option>')
            return ''.join(parts)

        def _opts_html_for_ranges(options_list, current):
            cur_num = _parse_range_val(current)
            parts = []
            for opt in options_list:
                opt_num = _parse_range_val(opt)
                sel = ''
                if current is not None:
                    if isinstance(current, str) and current == opt:
                        sel = ' selected'
                    else:
                        try:
                            if cur_num is not None and opt_num is not None and abs(cur_num - opt_num) < 1e-12:
                                sel = ' selected'
                        except Exception:
                            pass
                parts.append(f'<option value="{opt}"{sel}>{opt}</option>')
            return ''.join(parts)

        # read current settings for each key (fall back to defaults)
        def s(key):
            return self.settings.get(key, Keithley2602.DEFAULT_SETTINGS.get(key))

        # build per-control HTML fragments with current values marked/filled
        nplc_options_A = _opts_html_for_nplc(s('smua.nplc'))
        nplc_options_B = _opts_html_for_nplc(s('smub.nplc'))
        volt_options_A = _opts_html_for_ranges(volt_opts, s('smua.src_voltage_range'))
        volt_options_B = _opts_html_for_ranges(volt_opts, s('smub.src_voltage_range'))
        curr_options_A = _opts_html_for_ranges(curr_opts, s('smua.src_current_range'))
        curr_options_B = _opts_html_for_ranges(curr_opts, s('smub.src_current_range'))

        checked_a = ' checked' if bool(s('smua.output')) else ''
        checked_b = ' checked' if bool(s('smub.output')) else ''
        src_a = s('smua.source')
        src_b = s('smub.source')
        _a_v = s('smua.src_voltage_limit')
        _b_v = s('smub.src_voltage_limit')
        _a_i = s('smua.src_current_limit')
        _b_i = s('smub.src_current_limit')
        src_a_level = '' if _a_v is None else _a_v
        src_b_level = '' if _b_v is None else _b_v
        src_a_climit = '' if _a_i is None else _a_i
        src_b_climit = '' if _b_i is None else _b_i

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
            <div class="smu-col" id="{iid}-smu-A">
                <h4>SMU A</h4>
                <label>Output: <input type="checkbox" id="{iid}-smuA-output" data-key="smua.output"{checked_a} /></label>
                <label>NPLC: <select id="{iid}-smuA-nplc" data-key="smua.nplc">{nplc_options_A}</select></label>
                <label>Source: <select id="{iid}-smuA-source" data-key="smua.source"><option value="voltage"{' selected' if src_a=='voltage' else ''}>Voltage</option><option value="current"{' selected' if src_a=='current' else ''}>Current</option></select></label>
                <label>Source Voltage Range: <select id="{iid}-smuA-src-voltage-range" data-key="smua.src_voltage_range">{volt_options_A}</select></label>
                <label>Source Voltage Limit: <input id="{iid}-smuA-src-voltage-limit" type="number" step="any" data-key="smua.src_voltage_limit" value="{src_a_level}"/></label>
                <label>Source Current Range: <select id="{iid}-smuA-src-current-range" data-key="smua.src_current_range">{curr_options_A}</select></label>
                <label>Source Current Limit: <input id="{iid}-smuA-src-current-limit" type="number" step="any" data-key="smua.src_current_limit" value="{src_a_climit}"/></label>
                <label>Measure Voltage Range: <select id="{iid}-smuA-meas-voltage-range" data-key="smua.meas_voltage_range">{volt_options_A}</select></label>
                <label>Measure Current Range: <select id="{iid}-smuA-meas-current-range" data-key="smua.meas_current_range">{curr_options_A}</select></label>
            </div>
            <div class="smu-col" id="{iid}-smu-B">
                <h4>SMU B</h4>
                <label>Output: <input type="checkbox" id="{iid}-smuB-output" data-key="smub.output"{checked_b} /></label>
                <label>NPLC: <select id="{iid}-smuB-nplc" data-key="smub.nplc">{nplc_options_B}</select></label>
                <label>Source: <select id="{iid}-smuB-source" data-key="smub.source"><option value="voltage"{' selected' if src_b=='voltage' else ''}>Voltage</option><option value="current"{' selected' if src_b=='current' else ''}>Current</option></select></label>
                <label>Source Voltage Range: <select id="{iid}-smuB-src-voltage-range" data-key="smub.src_voltage_range">{volt_options_B}</select></label>
                <label>Source Voltage Limit: <input id="{iid}-smuB-src-voltage-limit" type="number" step="any" data-key="smub.src_voltage_limit" value="{src_b_level}"/></label>
                <label>Source Current Range: <select id="{iid}-smuB-src-current-range" data-key="smub.src_current_range">{curr_options_B}</select></label>
                <label>Source Current Limit: <input id="{iid}-smuB-src-current-limit" type="number" step="any" data-key="smub.src_current_limit" value="{src_b_climit}"/></label>
                <label>Measure Voltage Range: <select id="{iid}-smuB-meas-voltage-range" data-key="smub.meas_voltage_range">{volt_options_B}</select></label>
                <label>Measure Current Range: <select id="{iid}-smuB-meas-current-range" data-key="smub.meas_current_range">{curr_options_B}</select></label>
            </div>
    </div>
    <div class=\"device-plot\" style=\"height:240px\"></div>
    """
    def next(self):
        for i in (0,1):
            if self._sweeps_iter[i] is None:
                self._sweeps_iter[i] = iter(self.sweeps[i])
        for i, smux in enumerate(('smua', 'smub')):
            if self.settings[f'{smux}.output']:
                src = self.settings[f"{smux}.source"][0].lower()
                val = next(self._sweeps_iter[i])
                self.write(f'{smux}.level{src} = {val:0.6e}')
        return self.measure()
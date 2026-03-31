from InstrumentBase import InstrumentBase
try:
    import pyvisa
except Exception:
    pyvisa = None


class Keithley6430(InstrumentBase):
    """Minimal wrapper for a Keithley 6430 picoammeter-style instrument.

    Provides `open(address)`, `close()`, `update(settings)` and `measure()`.
    Designed to be API-compatible with the GUI and similar to Keithley2602,
    but exposes only one SMU-like channel (`smua`).
    """
    DEFAULT_SETTINGS = {
        "smua.output": False,
        "smua.nplc": 1,
        "smua.source": "current",
        "smua.src_current_range": "±10n",
        "smua.src_current_limit": 1e-8,
        "smua.meas_current_range": "±10n",
        "smua.meas_voltage_range": "±100mV",
        "smua.level": None,
    }

    def __init__(self):
        super().__init__()
        self.rm = None
        self.idn = None

    def get(self, smux: str, key: str | None = None):
        if key is not None:
            smux = f"{smux}.{key}"
        return super().get(smux)

    def open(self, address=None, timeout=5):
        if pyvisa is None:
            raise RuntimeError('pyvisa not available')
        self.rm = pyvisa.ResourceManager()
        resources = list(self.rm.list_resources())
        try_order = []
        if address:
            try_order.append(address)
        try_order.extend(r for r in resources if r not in try_order if 'GPIB' in r)
        try_order.extend(r for r in resources if r not in try_order)
        for res in try_order:
            try:
                inst = self.rm.open_resource(res, timeout=timeout * 1000)
                try:
                    idn = inst.query('*IDN?').strip()
                except Exception:
                    idn = None
                    continue
                if idn and '6430' in idn:
                    self.inst = inst
                    self.idn = idn
                    self.update(self.settings)
                    return True
                else:
                    try:
                        inst.close()
                    except Exception:
                        pass
            except Exception as e:
                print(f'ERROR: While trying to open instrument at address {res}, got exception', e)
        return False

    def update(self, settings: dict):
        allowed_fields = ('output', 'nplc', 'source', 'src_current_range', 'src_current_limit', 'meas_current_range', 'meas_voltage_range')
        allowed_keys = [f'smua.{f}' for f in allowed_fields]

        if 'smua.level' in settings:
            try:
                # Accept level as raw value or a simple list expression; store as given
                self.settings['smua.level'] = settings.pop('smua.level')
            except Exception:
                pass

        for k in settings.keys():
            if k not in allowed_keys:
                raise ValueError(f'Unsupported setting key: {k}')

        self.settings.update(settings)
        # normalize ± strings to numbers where present
        for k, v in list(self.settings.items()):
            if isinstance(v, str) and v.startswith('±'):
                try:
                    self.settings[k] = float(v[1:-1].replace('m', 'e-3').replace('u', 'e-6').replace('n', 'e-9'))
                except Exception:
                    pass

        if self.inst is None:
            return True

        smux = 'smua'
        out_flag = self.get(smux, 'output')

        # configure source function
        try:
            source = self.get(smux, 'source')
            if source == 'current':
                self.write(f'{smux}.source.func = {smux}.OUTPUT_DCAMPS')
                self.write(f'{smux}.source.leveli = 0')
                self.write(f'display.{smux}.measure.func = display.MEASURE_DCVOLTS')
            else:
                self.write(f'{smux}.source.func = {smux}.OUTPUT_DCVOLTS')
                self.write(f'{smux}.source.levelv = 0')
                self.write(f'display.{smux}.measure.func = display.MEASURE_DCAMPS')
        except Exception as e:
            print('ERROR: While trying to set source type', e)

        try:
            nplc = int(self.get(smux, 'nplc'))
            self.write(f'{smux}.measure.nplc = {nplc}')
        except Exception as e:
            print('ERROR: While trying to set NPLC', e)

        try:
            src_irange = float(self.get(smux, 'src_current_range'))
            mes_irange = float(self.get(smux, 'meas_current_range'))
            ilim = float(self.get(smux, 'src_current_limit')) or float(self.DEFAULT_SETTINGS.get('smua.src_current_limit'))
            self.write(f'{smux}.source.rangei = {src_irange:0.6e}')
            self.write(f'{smux}.measure.rangei = {mes_irange:0.6e}')
            self.write(f'{smux}.source.limiti = {ilim:0.6e}')
        except Exception as e:
            print('ERROR: While trying to set current range/limit', e)

        try:
            if out_flag:
                self.write(f'{smux}.source.output = {smux}.OUTPUT_ON')
            else:
                self.write(f'{smux}.source.output = {smux}.OUTPUT_OFF')
        except Exception as e:
            print('ERROR: While trying to set output', e)

        return True

    def measure(self):
        out = {'smua.v': None, 'smua.i': None, 'smua.setv': None, 'smua.seti': None}
        if self.inst is None:
            return out

        def _get(cmd, key):
            try:
                out[key] = self.query(cmd, float)
            except Exception:
                out[key] = None

        _get('printnumber(smua.measure.v())', 'smua.v')
        _get('printnumber(smua.measure.i())', 'smua.i')
        if self.settings.get('smua.source') == 'voltage':
            try:
                out['smua.setv'] = self.query('printnumber(smua.source.levelv)', float)
            except Exception:
                out['smua.setv'] = None
        else:
            try:
                out['smua.seti'] = self.query('printnumber(smua.source.leveli)', float)
            except Exception:
                out['smua.seti'] = None

        return out

    def card_html(self, iid: str, type_name: str = 'keithley6430') -> str:
        # simple control card for a single-channel instrument
        checked = ' checked' if bool(self.get('smua.output')) else ''
        nplc_list = list(range(1, 11))
        nplc_options = ''.join([f'<option value="{i}"{" selected" if str(self.get("smua.nplc"))==str(i) else ""}>{i}</option>' for i in nplc_list])
        curr_opts = ["±1n", "±10n", "±100n", "±1u", "±10u", "±100u"]
        def _opts(options_list, current):
            parts = []
            for opt in options_list:
                sel = ' selected' if str(current) == str(opt) else ''
                parts.append(f'<option value="{opt}"{sel}>{opt}</option>')
            return ''.join(parts)
        curr_options = _opts(curr_opts, self.get('smua.src_current_range'))
        meas_curr_options = _opts(curr_opts, self.get('smua.meas_current_range'))
        src_i_level = '' if self.get('smua.src_current_limit') is None else self.get('smua.src_current_limit')

        return f"""
    <h3>{type_name} <small>({iid})</small></h3>
    <p>Status: <span class=\"status\">closed</span> IDN: <span class=\"idn\">-</span></p>
    <div class=\"device-controls\">\n      <button class=\"open\">Open</button>\n      <button class=\"close\">Close</button>\n      <button class=\"remove\">Remove</button>\n    </div>
    <div class=\"smu-grid\">\n      <div class=\"smu-col\" id=\"{iid}-smu-A\">\n        <h4>Channel</h4>\n        <label>Output: <input type=\"checkbox\" data-key=\"smua.output\"{checked} /></label>\n        <label>NPLC: <select data-key=\"smua.nplc\">{nplc_options}</select></label>\n        <label>Source: <select data-key=\"smua.source\"><option value=\"current\"{' selected' if self.get('smua.source')=='current' else ''}>Current</option><option value=\"voltage\"{' selected' if self.get('smua.source')=='voltage' else ''}>Voltage</option></select></label>\n        <label>Source Current Range: <select data-key=\"smua.src_current_range\">{curr_options}</select></label>\n        <label>Source Current Limit: <input type=\"number\" step=\"any\" data-key=\"smua.src_current_limit\" value=\"{src_i_level}\"/></label>\n        <label>Measure Current Range: <select data-key=\"smua.meas_current_range\">{meas_curr_options}</select></label>\n        <label>Level: <input type=\"text\" data-key=\"smua.level\" value=\"{0}\"/></label>\n      </div>\n    </div>\n    <div class=\"device-plot\" style=\"height:240px\"></div>\n    """

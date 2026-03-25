document.addEventListener('DOMContentLoaded', () => {
  const statusEl = document.getElementById('status');
  const idnEl = document.getElementById('idn');
  const openBtn = document.getElementById('open');
  const closeBtn = document.getElementById('close');
  const refreshBtn = document.getElementById('refresh');
//   const addrInput = document.getElementById('address');
  const result = document.getElementById('result');
  // SMU controls
  const smuDefs = {
    // Allowed Keithley 2602 ranges
    voltageRanges: ["±100mV","±1V","±6V","±40V"],
    currentRanges: ["±100nA","±1uA","±10uA","±100uA","±1mA","±10mA","±100mA","±1A"],
    nplcs: Array.from({length:10},(_,i)=>i+1)
  };

  function populateSelect(id, options) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = '';
    options.forEach(o=>{
      const opt = document.createElement('option'); opt.value = o; opt.textContent = o; el.appendChild(opt);
    });
  }

  // populate options
  ['A','B'].forEach(s=>{
    populateSelect(`smu${s.toLowerCase()}-nplc`, smuDefs.nplcs);
    populateSelect(`smu${s.toLowerCase()}-src-voltage-range`, smuDefs.voltageRanges);
    populateSelect(`smu${s.toLowerCase()}-src-current-range`, smuDefs.currentRanges);
    populateSelect(`smu${s.toLowerCase()}-meas-voltage-range`, smuDefs.voltageRanges);
    populateSelect(`smu${s.toLowerCase()}-meas-current-range`, smuDefs.currentRanges);
  });

  async function fetchSMU(which) {
    const r = await fetch(`/api/smu/${which}`);
    const j = await r.json();
    const smu = j.smu || {};
    // populate fields
    const prefix = `smu${which.toLowerCase()}`;
    const set = (id, val) => {
      const el = document.getElementById(id); if (!el) return;
      if (el.type === 'checkbox') { el.checked = !!val; return; }
      // If it's a select, ensure the value exists in options; otherwise pick first option
      if (el.tagName === 'SELECT') {
        const has = Array.from(el.options).some(o => o.value == val);
        if (has) el.value = val; else if (el.options.length > 0) el.value = el.options[0].value;
        return;
      }
      el.value = val;
    };
    set(`${prefix}-output`, smu.output ?? false);
    set(`${prefix}-nplc`, smu.nplc ?? 1);
    set(`${prefix}-source`, smu.source ?? 'voltage');
    set(`${prefix}-src-voltage-range`, smu.src_voltage_range ?? smuDefs.voltageRanges[0]);
    set(`${prefix}-src-voltage-limit`, smu.src_voltage_limit ?? 0);
    set(`${prefix}-src-current-range`, smu.src_current_range ?? smuDefs.currentRanges[0]);
    set(`${prefix}-src-current-limit`, smu.src_current_limit ?? 0);
    set(`${prefix}-meas-voltage-range`, smu.meas_voltage_range ?? smuDefs.voltageRanges[0]);
    set(`${prefix}-meas-current-range`, smu.meas_current_range ?? smuDefs.currentRanges[0]);
  }

  async function updateSMU(which, data) {
    const r = await fetch(`/api/smu/${which}`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
    const j = await r.json();
    return j;
  }

  // wire change listeners
  function wireSMU(which) {
    const prefix = `smu${which.toLowerCase()}`;
    const fields = ['output','nplc','source','src-voltage-range','src-voltage-limit','src-current-range','src-current-limit','meas-voltage-range','meas-current-range'];
    fields.forEach(f=>{
      const id = `${prefix}-${f}`;
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('change', async ()=>{
        // prepare payload mapping IDs to server fields
        const payload = {};
        payload['output'] = document.getElementById(`${prefix}-output`).checked;
        payload['nplc'] = parseInt(document.getElementById(`${prefix}-nplc`).value,10);
        payload['source'] = document.getElementById(`${prefix}-source`).value;
        payload['src_voltage_range'] = document.getElementById(`${prefix}-src-voltage-range`).value;
        payload['src_voltage_limit'] = parseFloat(document.getElementById(`${prefix}-src-voltage-limit`).value || 0);
        payload['src_current_range'] = document.getElementById(`${prefix}-src-current-range`).value;
        payload['src_current_limit'] = parseFloat(document.getElementById(`${prefix}-src-current-limit`).value || 0);
        payload['meas_voltage_range'] = document.getElementById(`${prefix}-meas-voltage-range`).value;
        payload['meas_current_range'] = document.getElementById(`${prefix}-meas-current-range`).value;
        await updateSMU(which, payload);
      });
    });

    // nothing special for checkbox
  }


  async function fetchStatus() {
    try {
      const r = await fetch('/api/status');
      const j = await r.json();
      statusEl.textContent = j.status || '-';
      idnEl.textContent = j.idn || '-';
    } catch (e) {
      statusEl.textContent = 'error';
      idnEl.textContent = '-';
    }
  }

  openBtn.addEventListener('click', async () => {
    result.textContent = 'Opening...';
    // const addr = addrInput.value.trim() || undefined;
    try {
      const r = await fetch('/api/open', { method: 'POST', headers: {'Content-Type': 'application/json'} });
      const j = await r.json();
      if (r.ok) {
        result.textContent = `Status: ${j.status}`;
        statusEl.textContent = j.status || '-';
        idnEl.textContent = j.idn || '-';
      } else {
        result.textContent = j.error || 'open failed';
      }
    } catch (e) {
      result.textContent = 'open error: ' + e;
    }
  });

  closeBtn.addEventListener('click', async () => {
    result.textContent = 'Closing...';
    try {
      const r = await fetch('/api/close', { method: 'POST' });
      const j = await r.json();
      if (r.ok) {
        result.textContent = `Status: ${j.status}`;
        statusEl.textContent = j.status || '-';
        idnEl.textContent = '-';
      } else {
        result.textContent = j.error || 'close failed';
      }
    } catch (e) {
      result.textContent = 'close error';
    }
  });

  refreshBtn.addEventListener('click', fetchStatus);

  // initial
  fetchStatus();
  // fetch and wire SMUs
  fetchSMU('A').then(()=>wireSMU('A'));
  fetchSMU('B').then(()=>wireSMU('B'));
});

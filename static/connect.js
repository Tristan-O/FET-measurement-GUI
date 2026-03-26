document.addEventListener('DOMContentLoaded', () => {
  const addBtn = document.getElementById('add-inst');
  const typeSel = document.getElementById('inst-type');
  const devicesDiv = document.getElementById('devices');

  async function addInstrument() {
    const t = typeSel.value;
    try {
      const r = await fetch('/api/instrument/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ type: t }) });
      const j = await r.json();
      if (r.ok) {
        await createDeviceCard(j.id, j.type);
      } else {
        alert('Failed to add: ' + (j.error || r.statusText));
      }
    } catch (e) { alert('Add error: ' + e); }
  }

  async function createDeviceCard(id, type) {
    const card = document.createElement('div');
    card.className = 'device-card';
    card.id = `dev-${id}`;
    card.dataset.type = type;
    devicesDiv.appendChild(card);

    // Request server-generated HTML for this card. Fall back to client template on error.
    try {
      const r = await fetch(`/api/instrument/${id}/card`);
      const j = await r.json();
      if (r.ok && j.html) {
        card.innerHTML = j.html;
      } else {
        throw new Error('no html');
      }
    } catch (e) {
      // fallback: simple client-side template similar to previous behavior
      card.innerHTML = `\n      <h3>${type} <small>(${id})</small></h3>\n      <p>Status: <span class=\"status\">closed</span> IDN: <span class=\"idn\">-</span></p>\n      <div class=\"device-controls\">\n        <button class=\"open\">Open</button>\n        <button class=\"close\">Close</button>\n        <button class=\"force\">Force Update</button>\n        <button class=\"remove\">Remove</button>\n      </div>\n      <div class=\"smu-grid\">\n        <div class=\"smu-col\" id=\"${id}-smu-A\">\n          <h4>SMU A</h4>\n          <label>Output: <input type=\"checkbox\" id=\"${id}-smuA-output\" /></label>\n          <label>NPLC: <select id=\"${id}-smuA-nplc\"></select></label>\n          <label>Source: <select id=\"${id}-smuA-source\"><option value=\"voltage\">Voltage</option><option value=\"current\">Current</option></select></label>\n          <label>Source Voltage Range: <select id=\"${id}-smuA-src-voltage-range\"></select></label>\n          <label>Source Voltage Limit: <input id=\"${id}-smuA-src-voltage-limit\" type=\"number\" step=\"any\"/></label>\n          <label>Source Current Range: <select id=\"${id}-smuA-src-current-range\"></select></label>\n          <label>Source Current Limit: <input id=\"${id}-smuA-src-current-limit\" type=\"number\" step=\"any\"/></label>\n          <label>Measure Voltage Range: <select id=\"${id}-smuA-meas-voltage-range\"></select></label>\n          <label>Measure Current Range: <select id=\"${id}-smuA-meas-current-range\"></select></label>\n        </div>\n        <div class=\"smu-col\" id=\"${id}-smu-B\">\n          <h4>SMU B</h4>\n          <label>Output: <input type=\"checkbox\" id=\"${id}-smuB-output\" /></label>\n          <label>NPLC: <select id=\"${id}-smuB-nplc\"></select></label>\n          <label>Source: <select id=\"${id}-smuB-source\"><option value=\"voltage\">Voltage</option><option value=\"current\">Current</option></select></label>\n          <label>Source Voltage Range: <select id=\"${id}-smuB-src-voltage-range\"></select></label>\n          <label>Source Voltage Limit: <input id=\"${id}-smuB-src-voltage-limit\" type=\"number\" step=\"any\"/></label>\n          <label>Source Current Range: <select id=\"${id}-smuB-src-current-range\"></select></label>\n          <label>Source Current Limit: <input id=\"${id}-smuB-src-current-limit\" type=\"number\" step=\"any\"/></label>\n          <label>Measure Voltage Range: <select id=\"${id}-smuB-meas-voltage-range\"></select></label>\n          <label>Measure Current Range: <select id=\"${id}-smuB-meas-current-range\"></select></label>\n        </div>\n      </div>\n      <div class=\"device-plot\" style=\"height:240px\"></div>\n    `;
    }

    const openBtn = card.querySelector('button.open');
    const closeBtn = card.querySelector('button.close');
    const removeBtn = card.querySelector('button.remove');
    const forceBtn = card.querySelector('button.force');
    const statusEl = card.querySelector('.status');
    const idnEl = card.querySelector('.idn');
    const plotDiv = card.querySelector('.device-plot');

    // SMU option sets
    const smuDefs = {
      voltageRanges: ["±100mV","±1V","±6V","±40V"],
      currentRanges: ["±100nA","±1uA","±10uA","±100uA","±1mA","±10mA","±100mA","±1A"],
      nplcs: Array.from({length:10},(_,i)=>i+1)
    };

    function populateSelectElem(sel, options) {
      if (!sel) return;
      sel.innerHTML = '';
      options.forEach(o=>{ const opt = document.createElement('option'); opt.value = o; opt.textContent = o; sel.appendChild(opt); });
    }

    async function fetchAndPopulateSMU(which) {
      try {
        const r = await fetch(`/api/instrument/${id}/update`);
        const j = await r.json();
        // server returns { smus: { A: {...}, B: {...} } } for GET
        const smus = j.smus || {};
        const smu = smus[which] || {};
        const prefix = `${id}-smu${which}`;
        const set = (elid, val) => {
          const el = document.getElementById(elid); if (!el) return;
          if (el.type === 'checkbox') { el.checked = !!val; return; }
          if (el.tagName === 'SELECT') {
            const has = Array.from(el.options).some(o=>o.value==val);
            if (has) el.value = val; else if (el.options.length>0) el.value = el.options[0].value;
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
      } catch (e) {
        console.warn('fetchAndPopulateSMU error', e);
      }
    }

    function wireSMU(which) {
      const prefix = `${id}-smu${which}`;
      const fields = ['output','nplc','source','src-voltage-range','src-voltage-limit','src-current-range','src-current-limit','meas-voltage-range','meas-current-range'];
      fields.forEach(f=>{
        const el = document.getElementById(`${prefix}-${f}`);
        if (!el) return;
        el.addEventListener('change', async ()=>{
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
          try {
            // Build generic payload per-device type. For a Keithley 2602 send { a: {...}, b: {...} }
            const devType = card.dataset.type;
            if (devType === 'keithley2602') {
              const inner = {};
              inner['output'] = payload['output'];
              inner['nplc'] = payload['nplc'];
              inner['source'] = payload['source'];
              inner['src_voltage_range'] = payload['src_voltage_range'];
              inner['src_voltage_limit'] = payload['src_voltage_limit'];
              inner['src_current_range'] = payload['src_current_range'];
              inner['src_current_limit'] = payload['src_current_limit'];
              inner['meas_voltage_range'] = payload['meas_voltage_range'];
              inner['meas_current_range'] = payload['meas_current_range'];
              const dataToSend = {};
              dataToSend[which.toLowerCase()] = inner;
              await fetch(`/api/instrument/${id}/update`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(dataToSend) });
            } else {
              // fallback: include 'which' in payload for the generic update endpoint
              payload.which = which;
              await fetch(`/api/instrument/${id}/update`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
            }
          } catch (e) { console.warn('apply smu failed', e); }
        });
      });
    }

    // populate select options for both SMUs
    ['A','B'].forEach(s=>{
      populateSelectElem(document.getElementById(`${id}-smu${s}-nplc`), smuDefs.nplcs);
      populateSelectElem(document.getElementById(`${id}-smu${s}-src-voltage-range`), smuDefs.voltageRanges);
      populateSelectElem(document.getElementById(`${id}-smu${s}-src-current-range`), smuDefs.currentRanges);
      populateSelectElem(document.getElementById(`${id}-smu${s}-meas-voltage-range`), smuDefs.voltageRanges);
      populateSelectElem(document.getElementById(`${id}-smu${s}-meas-current-range`), smuDefs.currentRanges);
      fetchAndPopulateSMU(s).then(()=>wireSMU(s));
    });

    openBtn.addEventListener('click', async ()=>{
      try {
        const r = await fetch(`/api/instrument/${id}/open`, { method: 'POST' });
        const j = await r.json();
        if (r.ok) {
          statusEl.textContent = j.status || 'opened';
          idnEl.textContent = j.idn || '-';
        } else {
          alert('Open failed: ' + (j.error || r.statusText));
        }
      } catch (e) { alert('Open error: ' + e); }
    });

    closeBtn.addEventListener('click', async ()=>{
      try {
        const r = await fetch(`/api/instrument/${id}/close`, { method: 'POST' });
        const j = await r.json();
        if (r.ok) {
          statusEl.textContent = 'closed';
          idnEl.textContent = '-';
        } else {
          alert('Close failed');
        }
      } catch (e) { alert('Close error: ' + e); }
    });

    removeBtn.addEventListener('click', async ()=>{
      if (!confirm('Remove device?')) return;
      try {
        const r = await fetch(`/api/instrument/${id}`, { method: 'DELETE' });
        if (r.ok) card.remove(); else alert('Remove failed');
      } catch (e) { alert('Remove error: ' + e); }
    });

    forceBtn.addEventListener('click', async ()=>{
      try {
        const r = await fetch(`/api/instrument/${id}/force_update`, { method: 'POST' });
        const j = await r.json();
        if (r.ok) {
          // simple visual: update plot with returned meas
          const meas = j.meas || {};
          // expect flat keys A_v/A_i/B_v/B_i
          const ts = (new Date()).toISOString();
          plotDiv.textContent = JSON.stringify(meas);
        } else alert('Force failed');
      } catch (e) { alert('Force error: ' + e); }
    });
  }

  addBtn.addEventListener('click', addInstrument);
});

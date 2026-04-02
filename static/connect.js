document.addEventListener('DOMContentLoaded', () => {
  const SAVE_NOTES_KEY = 'notesFromLastSave';
  const addBtn = document.getElementById('add-inst');
  const typeSel = document.getElementById('inst-type');
  const devicesDiv = document.getElementById('devices');

  async function addInstrument() {
    const type = typeSel.value;
    try {
      const r = await fetch('/api/instrument/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({type}) });
      const j = await r.json();
      const iid = j.id || j.iid;
      if (r.ok && iid) createDeviceCard(iid, j.type || type);
      else alert('Add failed: ' + (j.error || r.statusText));
    } catch (e) { alert('Add error: ' + e); }
  }

  async function loadExistingInstruments() {
    try {
      const r = await fetch('/api/instruments');
      const j = await r.json();
      const list = j.instruments || [];
      list.forEach(inst => createDeviceCard(inst.id, inst.type || 'device'));
    } catch (e) { console.warn('loadExistingInstruments error', e); }
  }

  function createDeviceCard(id, type) {
    const card = document.createElement('div');
    card.className = 'device-card';
    card.dataset.iid = id;
    devicesDiv.appendChild(card);

    // Fetch the HTML for the card from the backend. If unavailable, show minimal placeholder.
    fetch(`/api/instrument/${id}/card`).then(async r => {
      try {
        const j = await r.json();
        if (j && j.html) card.innerHTML = j.html;
        else card.innerHTML = `<h3>${type} <small>(${id})</small></h3><p>No card HTML from server.</p>`;
      } catch (e) {
        card.innerHTML = `<h3>${type} <small>(${id})</small></h3><p>No card HTML from server.</p>`;
      }
    }).catch(() => {
      card.innerHTML = `<h3>${type} <small>(${id})</small></h3><p>No card HTML from server.</p>`;
    }).finally(() => {
      setupCard(card);
    });
  }

  // Generic setup: populate controls (identified by data-key) and wire change handlers
  async function setupCard(cardEl) {
    const id = cardEl.dataset.iid;
    // query UI elements that may be present after card HTML is inserted
    const openBtn = cardEl.querySelector('button.open');
    const closeBtn = cardEl.querySelector('button.close');
    const removeBtn = cardEl.querySelector('button.remove');
    const forceBtn = cardEl.querySelector('button.force');
    const statusEl = cardEl.querySelector('.status');
    const idnEl = cardEl.querySelector('.idn');
    const plotDiv = cardEl.querySelector('.device-plot');

    try {
      const r = await fetch(`/api/instrument/${id}/update`);
      const j = await r.json();
      const settings = j.settings || {};

      const elems = Array.from(cardEl.querySelectorAll('[data-key]'));

      elems.forEach(el => {
        el.addEventListener('change', async () => {
          const payload = {};
          const all = Array.from(cardEl.querySelectorAll('[data-key]'));
          all.forEach(e => {
            const k = e.dataset.key; if (!k) return;
            if (e.type === 'checkbox') payload[k] = !!e.checked;
            else if (e.tagName === 'SELECT') {
              if (k.endsWith('.nplc')) payload[k] = parseInt(e.value, 10);
              else payload[k] = e.value;
            } else if (e.type === 'number') payload[k] = parseFloat(e.value || 0);
            else payload[k] = e.value;
          });
          try { 
            await fetch(`/api/instrument/${id}/update`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
          } catch (err) { 
            console.warn('update failed', err); 
          }
        });
      });

    } catch (e) { console.warn('setupCard error', e); }

    if (openBtn) openBtn.addEventListener('click', async ()=>{
      try { 
        const r = await fetch(`/api/instrument/${id}/open`, { method: 'POST' });
        const j = await r.json();
        if (statusEl) statusEl.textContent = j.status;
        if (r.ok) { 
          if (idnEl) idnEl.textContent = j.idn || '-';
        } else {
          alert('Open failed: ' + (j.error || r.statusText));
        }
      } catch (e) { 
        alert('Open error: ' + e);
      }
    });

    if (closeBtn) closeBtn.addEventListener('click', async ()=>{
      try { 
        const r = await fetch(`/api/instrument/${id}/close`, { method: 'POST' });
        const j = await r.json();
        if (statusEl) statusEl.textContent = j.status;
        if (!r.ok) {
          alert('Close failed');
        }
      } catch (e) {
        alert('Close error: ' + e); 
      }
    });

    if (removeBtn) removeBtn.addEventListener('click', async ()=>{
      if (!confirm('Remove device?')) return;
      try { 
        const r = await fetch(`/api/instrument/${id}`, { method: 'DELETE' });
        if (r.ok) cardEl.remove();
        else alert('Remove failed');
      } catch (e) { alert('Remove error: ' + e);

       }
    });

    if (forceBtn) forceBtn.addEventListener('click', async ()=>{
      try { 
        const r = await fetch(`/api/instrument/${id}/force_update`, { method: 'POST' });
        const j = await r.json();
        if (r.ok) { 
          const meas = j.meas || {};
          if (plotDiv) plotDiv.textContent = JSON.stringify(meas);
        } else {
          alert('Force failed'); 
        }
      } catch (e) { 
        alert('Force error: ' + e);
      }
    });
  }

  addBtn.addEventListener('click', addInstrument);
  loadExistingInstruments();

  // Stream control buttons (global for the page)
  const startBtn = document.getElementById('start-measure');
  const pauseBtn = document.getElementById('pause-measure');
  const stopBtn = document.getElementById('stop-measure');
  const saveBtn = document.getElementById('save-measure');
  const clearBtn = document.getElementById('clear-measure');

  if (startBtn) startBtn.addEventListener('click', async () => {
    try {
      const r = await fetch('/api/measure/start', { method: 'POST' });
      if (!r.ok) alert('Start failed');
    } catch (e) { alert('Start error: ' + e); }
  });

  if (pauseBtn) pauseBtn.addEventListener('click', async () => {
    try {
      const r = await fetch('/api/measure/pause', { method: 'POST' });
      if (!r.ok) alert('Pause failed');
    } catch (e) { alert('Pause error: ' + e); }
  });

  if (stopBtn) stopBtn.addEventListener('click', async () => {
    try {
      const r = await fetch('/api/measure/stop', { method: 'POST' });
      if (!r.ok) alert('Stop failed');
    } catch (e) { alert('Stop error: ' + e); }
  });

  if (saveBtn) saveBtn.addEventListener('click', async () => {
    const prevNotes = localStorage.getItem(SAVE_NOTES_KEY) || '';
    const notes = prompt('Enter notes for this measurement save:', prevNotes);
    if (notes === null) return;
    localStorage.setItem(SAVE_NOTES_KEY, notes);
    try {
      const r = await fetch('/api/measure/save', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ notes })
      });
      const j = await r.json();
      if (!r.ok) {
        alert('Save failed: ' + (j.error || r.statusText));
        return;
      }
      alert('Saved to ' + (j.file || 'data folder'));
    } catch (e) { alert('Save error: ' + e); }
  });

  if (clearBtn) clearBtn.addEventListener('click', async () => {
    if (!confirm('Clear current streamed data from memory?')) return;
    try {
      const r = await fetch('/api/measure/clear', { method: 'POST' });
      const j = await r.json();
      if (!r.ok) {
        alert('Clear failed: ' + (j.error || r.statusText));
        return;
      }
      alert('Stream data cleared.');
    } catch (e) { alert('Clear error: ' + e); }
  });
});

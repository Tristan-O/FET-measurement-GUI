document.addEventListener('DOMContentLoaded', () => {
  const statusEl = document.getElementById('status');
  const idnEl = document.getElementById('idn');
  const openBtn = document.getElementById('open');
  const closeBtn = document.getElementById('close');
  const refreshBtn = document.getElementById('refresh');
//   const addrInput = document.getElementById('address');
  const result = document.getElementById('result');

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
});

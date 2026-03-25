document.addEventListener('DOMContentLoaded', () => {
  const statusEl = document.getElementById('status');
  const idnEl = document.getElementById('idn');
  const refreshBtn = document.getElementById('refresh-status');
  const uploadForm = document.getElementById('upload-form');
  const uploadResult = document.getElementById('upload-result');
  const dataMeta = document.getElementById('data-meta');
  const tableWrap = document.getElementById('table-wrap');

  async function fetchStatus() {
    statusEl.textContent = 'checking...';
    idnEl.textContent = '-';
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

  async function fetchDataAndRender() {
    tableWrap.innerHTML = '';
    dataMeta.textContent = '';
    try {
      const r = await fetch('/api/data');
      const j = await r.json();
      const uploads = j.uploads || [];
      if (uploads.length === 0) {
        dataMeta.textContent = 'No data loaded.';
        return;
      }

      // Build transposed table: each upload is a column with filename as header
      const table = document.createElement('table');
      const thead = document.createElement('thead');
      const headerRow = document.createElement('tr');
      uploads.forEach(u => {
        const th = document.createElement('th');
        th.textContent = u.filename || '';
        th.title = u.filename || '';
        headerRow.appendChild(th);
      });
      thead.appendChild(headerRow);
      table.appendChild(thead);

      const tbody = document.createElement('tbody');
      const maxHeaders = Math.max(...uploads.map(u => (u.headers || []).length));
      for (let rowIdx = 0; rowIdx < maxHeaders; rowIdx++) {
        const tr = document.createElement('tr');
        uploads.forEach(u => {
          const td = document.createElement('td');
          const hdr = (u.headers || [])[rowIdx];
          if (hdr !== undefined) {
            const span = document.createElement('span');
            span.className = 'col-entry';
            span.textContent = hdr;
            span.dataset.uploadId = u.id;
            span.dataset.name = hdr;
            span.style.padding = '2px 6px';
            span.style.marginRight = '6px';
            span.style.display = 'inline-block';
            span.style.border = '1px solid transparent';
            span.style.cursor = 'pointer';
            span.addEventListener('dblclick', onHeaderDblClick);
            td.appendChild(span);
          }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      }

      table.appendChild(tbody);
      tableWrap.appendChild(table);
    } catch (e) {
      dataMeta.textContent = 'Error loading data';
    }
  }

  function onHeaderDblClick(ev) {
    const span = ev.currentTarget;
    const oldName = span.textContent;
    const uploadId = parseInt(span.dataset.uploadId, 10);
    const input = document.createElement('input');
    input.type = 'text';
    input.value = oldName;
    input.style.minWidth = '120px';
    span.replaceWith(input);
    input.focus();

    function finish() {
      const newName = input.value.trim();
      if (newName === '') {
        // revert
        input.replaceWith(span);
        return;
      }
      if (newName === oldName) {
        input.replaceWith(span);
        return;
      }
      // send rename request
      fetch('/api/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: uploadId, old_name: oldName, new_name: newName })
      }).then(res => res.json()).then(js => {
        if (js.ok) {
          // update UI: replace input with new span
          const newSpan = document.createElement('span');
          newSpan.className = 'col-entry';
          newSpan.textContent = newName;
          newSpan.dataset.uploadId = uploadId;
          newSpan.dataset.name = newName;
          newSpan.style.padding = '2px 6px';
          newSpan.style.marginRight = '6px';
          newSpan.style.display = 'inline-block';
          newSpan.style.border = '1px solid transparent';
          newSpan.style.cursor = 'pointer';
          newSpan.addEventListener('dblclick', onHeaderDblClick);
          input.replaceWith(newSpan);
        } else {
          input.replaceWith(span);
          alert(js.error || 'Rename failed');
        }
      }).catch(_ => {
        input.replaceWith(span);
        alert('Rename failed');
      });
    }

    input.addEventListener('blur', finish);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        finish();
      } else if (e.key === 'Escape') {
        input.replaceWith(span);
      }
    });
  }

  refreshBtn.addEventListener('click', fetchStatus);

  uploadForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    uploadResult.textContent = 'Uploading...';
    const fileInput = document.getElementById('file-input');
    if (!fileInput.files || fileInput.files.length === 0) {
      uploadResult.textContent = 'No file selected.';
      return;
    }
    const fd = new FormData();
    fd.append('file', fileInput.files[0]);
    try {
      const r = await fetch('/api/upload', { method: 'POST', body: fd });
      const j = await r.json();
      if (r.ok) {
        uploadResult.textContent = `Loaded ${j.parsed.headers.length} columns, ${j.parsed.rows_count} rows`;
        await fetchDataAndRender();
      } else {
        uploadResult.textContent = j.error || 'Upload failed';
      }
    } catch (e) {
      uploadResult.textContent = 'Upload error: ' + e;
    }
  });

  // initial load
  fetchStatus();
  fetchDataAndRender();
});

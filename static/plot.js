let DATASETS = []; // {key, upload_id, filename, name, array}
let plotCount = 0;
const PLOTS = {}; // id -> {divId, traceMap, xKey, lastIdx, refreshFn}
let STREAM_ES = null;

function restartStream() {
  if (STREAM_ES) {
    try { STREAM_ES.close(); } catch (e) { /* ignore */ }
    STREAM_ES = null;
  }
  STREAM_ES = setupStream();
}

async function fetchFull() {
  const r = await fetch('/api/full');
  const j = await r.json();
  const uploads = j.uploads || [];
  DATASETS = [];
  uploads.forEach(u => {
    (u.columns || []).forEach(col => {
      DATASETS.push({
        upload_id: u.id,
        filename: u.filename,
        name: col.name,
        array: col.array
      });
    });
  });

  // Requirement: whenever we pull fresh data from /api/full,
  // restart the live stream connection.
  restartStream();
}

function makeSelect(options, multiple=false) {
  const sel = document.createElement('select');
  if (multiple) sel.multiple = true;
  options.forEach(opt => {
    const o = document.createElement('option');
    o.value = opt.key;
    o.textContent = opt.label;
    sel.appendChild(o);
  });
  return sel;
}

function datasetKey(d) { return `${d.upload_id}||${d.name}`; }

function buildOptions() {
  return DATASETS.map(d => ({ key: datasetKey(d), label: `${d.filename} — ${d.name}` }));
}

function getDatasetByKey(key) {
  const parts = key.split('||');
  const uid = parseInt(parts[0],10);
  const name = parts.slice(1).join('||');
  return DATASETS.find(d=>d.upload_id===uid && d.name===name);
}

function appendStreamRowToDatasets(row) {
  Object.entries(row || {}).forEach(([name, value]) => {
    let ds = DATASETS.find(d => d.upload_id === 0 && d.name === name);
    if (!ds) {
      ds = { upload_id: 0, filename: '', name: name, array: [] };
      DATASETS.push(ds);
    }
    if (!Array.isArray(ds.array)) ds.array = [];
    ds.array.push(value);
  });
}

function replaceStreamUploadInDatasets(streamUpload) {
  // Drop current synthetic stream dataset entries.
  DATASETS = DATASETS.filter(d => d.upload_id !== 0);
  if (!streamUpload || !Array.isArray(streamUpload.columns)) return;
  streamUpload.columns.forEach(col => {
    DATASETS.push({
      upload_id: 0,
      filename: streamUpload.filename || '',
      name: col.name,
      array: Array.isArray(col.array) ? col.array : []
    });
  });
}

function parseSliceIndex(raw) {
  const s = (raw || '').trim();
  if (s === '') return undefined;
  const n = parseInt(s, 10);
  return Number.isNaN(n) ? undefined : n;
}

function addPlot() {
  plotCount += 1;
  const id = `plot_${plotCount}`;
  const container = document.createElement('div');
  container.className = 'plot-block';
  container.innerHTML = `
    <div class="plot-left">
      <div class="plot-controls">
        <div class="control-row">
          <label>X:</label>
          <span class="xsel"></span>
        </div>
        <div class="control-row">
          <label>Y:</label>
          <span class="ysel"></span>
        </div>
        <div class="control-row">
          <label><input type="checkbox" class="xlog" /> Log X</label>
          <label><input type="checkbox" class="ylog" /> Log Y</label>
          <label>Start: <input type="text" class="slice-start" placeholder="" size="6" /></label>
          <label>End: <input type="text" class="slice-end" placeholder="" size="6" /></label>
        </div>
        <div class="control-row">
          <button class="remove-plot">Remove</button>
        </div>
      </div>
    </div>
    <div class="plot-right">
      <div id="${id}" class="plot-area"></div>
    </div>
  `;
  document.getElementById('plots').appendChild(container);

  const opts = buildOptions();
  const xsel = makeSelect(opts, false);
  const ysel = makeSelect(opts, true);
  container.querySelector('.xsel').appendChild(xsel);
  container.querySelector('.ysel').appendChild(ysel);

  async function updatePlot(refreshFromServer=true) {
    if (refreshFromServer) await fetchFull();
    const xKey = xsel.value;
    const yKeys = Array.from(ysel.selectedOptions).map(o=>o.value);
    const startRaw = container.querySelector('.slice-start')?.value || '';
    const endRaw = container.querySelector('.slice-end')?.value || '';
    const sliceStart = parseSliceIndex(startRaw);
    const sliceEnd = parseSliceIndex(endRaw);
    const traces = [];
    const xset = xKey ? getDatasetByKey(xKey) : null;
    yKeys.forEach(yk => {
      const yset = getDatasetByKey(yk);
      if (!yset) return;
      const yBase = (yset.array || []);
      const xBase = xset ? (xset.array || []) : yBase.map((_, i) => i);
      const n = Math.min(xBase.length, yBase.length);
      const xSliced = xBase.slice(0, n).slice(sliceStart, sliceEnd);
      const ySliced = yBase.slice(0, n).slice(sliceStart, sliceEnd);
      traces.push({ x: xSliced, y: ySliced, name: `${yset.filename}:${yset.name}` });
    });
    const xlog = container.querySelector('.xlog').checked;
    const ylog = container.querySelector('.ylog').checked;
    // Keep user zoom/pan while data streams; reset view only when plot config changes.
    const viewRevision = `${xKey}|${yKeys.join(',')}|${sliceStart ?? ''}|${sliceEnd ?? ''}|${xlog ? 'log' : 'linear'}|${ylog ? 'log' : 'linear'}`;
    const layout = {
      margin:{t:30},
      xaxis:{type: xlog ? 'log' : 'linear'},
      yaxis:{type: ylog ? 'log' : 'linear'},
      uirevision: viewRevision
    };
    Plotly.react(id, traces, layout);

    // Register plot for live updates: map datasetKey -> trace index
    const traceMap = {};
    for (let i = 0; i < yKeys.length; ++i) traceMap[yKeys[i]] = i;
    // determine current stream length to avoid duplicating existing points
    let lastIdx = 0;
    if (xset && xset.upload_id === 0 && Array.isArray(xset.array)) lastIdx = xset.array.length;
    PLOTS[id] = { divId: id, traceMap: traceMap, xKey: xKey, lastIdx: lastIdx, refreshFn: updatePlot };
  }

  xsel.addEventListener('change', updatePlot);
  ysel.addEventListener('change', updatePlot);
  const xlog = container.querySelector('.xlog');
  const ylog = container.querySelector('.ylog');
  if (xlog) xlog.addEventListener('change', updatePlot);
  if (ylog) ylog.addEventListener('change', updatePlot);
  const sliceStartInput = container.querySelector('.slice-start');
  const sliceEndInput = container.querySelector('.slice-end');
  if (sliceStartInput) sliceStartInput.addEventListener('change', updatePlot);
  if (sliceEndInput) sliceEndInput.addEventListener('change', updatePlot);
  // (Add Y removed - multi-select already available)

  container.querySelector('.remove-plot').addEventListener('click', ()=>{
    // remove plot registry and DOM
    delete PLOTS[id];
    container.remove();
  });

  // initial plot: set sensible defaults
  if (opts.length > 0) {
    xsel.value = opts[0].key;
    if (ysel.options.length > 0) ysel.options[0].selected = true;
  }
  updatePlot();
}

// SSE handler for live stream updates
function setupStream() {
  if (typeof(EventSource) === 'undefined') return;
  const es = new EventSource('/api/measure/stream');
  es.onmessage = (evt) => {
    try {
      const row = JSON.parse(evt.data);
      if (row && row.clear) {
        // Server indicates stream was cleared/reset; replace stream data and refresh plots.
        replaceStreamUploadInDatasets(row.full);
        Object.values(PLOTS).forEach(plot => {
          if (typeof plot.refreshFn === 'function') plot.refreshFn(false);
        });
        return;
      }
      // Keep stream dataset arrays current, then redraw affected plots.
      appendStreamRowToDatasets(row);
      Object.values(PLOTS).forEach(plot => {
        const usesStreamX = !!(plot.xKey && plot.xKey.startsWith('0||'));
        const usesStreamY = Object.keys(plot.traceMap || {}).some(k => k.startsWith('0||'));
        if (!usesStreamX && !usesStreamY) return;
        if (typeof plot.refreshFn === 'function') {
          plot.refreshFn(false);
        }
      });
    } catch (e) { console.warn('stream parse error', e); }
  };
  es.onerror = (e) => { /* keep connection open */ };
  return es;
}

// Streaming moved to the acquire page.

async function init() {
  await fetchFull();
  // Add first plot
  addPlot();
  document.getElementById('add-plot').addEventListener('click', addPlot);
  // plot page no longer manages the live stream
}

window.addEventListener('DOMContentLoaded', init);

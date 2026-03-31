let DATASETS = []; // {key, upload_id, filename, name, array}
let plotCount = 0;
const PLOTS = {}; // id -> {divId, traceMap, xKey, lastIdx}
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

  async function updatePlot() {
    await fetchFull();
    const xKey = xsel.value;
    const yKeys = Array.from(ysel.selectedOptions).map(o=>o.value);
    const startRaw = (container.querySelector('.slice-start')?.value || '').trim();
    const endRaw = (container.querySelector('.slice-end')?.value || '').trim();
    const sliceStart = startRaw === '' ? undefined : parseInt(startRaw, 10);
    const sliceEnd = endRaw === '' ? undefined : parseInt(endRaw, 10);
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
    const layout = { margin:{t:30}, xaxis:{type: xlog ? 'log' : 'linear'}, yaxis:{type: ylog ? 'log' : 'linear'} };
    Plotly.newPlot(id, traces, layout);

    // Register plot for live updates: map datasetKey -> trace index
    const traceMap = {};
    for (let i = 0; i < yKeys.length; ++i) traceMap[yKeys[i]] = i;
    // determine current stream length to avoid duplicating existing points
    let lastIdx = 0;
    if (xset && xset.upload_id === 0 && Array.isArray(xset.array)) lastIdx = xset.array.length;
    PLOTS[id] = { divId: id, traceMap: traceMap, xKey: xKey, lastIdx: lastIdx };
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
      // row is a single sample with flat keys like {ts, A_v, A_i, B_v, B_i}
      Object.values(PLOTS).forEach(plot => {
        const xKey = plot.xKey;
        if (!xKey || !xKey.startsWith('0||')) return; // require stream X
        const xName = xKey.split('||').slice(1).join('||');
        const xVal = row[xName];
        Object.entries(plot.traceMap).forEach(([dkey, traceIndex]) => {
          if (!dkey.startsWith('0||')) return;
          const yName = dkey.split('||').slice(1).join('||');
          const yVal = row[yName];
          if (yVal === undefined) return;
          const update = { x: [[ xVal ]], y: [[ yVal ]] };
          try { Plotly.extendTraces(plot.divId, update, [traceIndex]); }
          catch (e) { console.warn('extendTraces failed', e); }
        });
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

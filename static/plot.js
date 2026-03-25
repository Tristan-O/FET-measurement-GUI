let DATASETS = []; // {key, upload_id, filename, name, array}
let plotCount = 0;

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
    <div class="plot-controls">
      X: <span class="xsel"></span>
      Y: <span class="ysel"></span>
      <button class="add-y">Add Y</button>
      <button class="remove-plot">Remove</button>
    </div>
    <div id="${id}" class="plot-area" style="height:400px;"></div>
  `;
  document.getElementById('plots').appendChild(container);

  const opts = buildOptions();
  const xsel = makeSelect(opts, false);
  const ysel = makeSelect(opts, true);
  container.querySelector('.xsel').appendChild(xsel);
  container.querySelector('.ysel').appendChild(ysel);

  function updatePlot() {
    const xKey = xsel.value;
    const yKeys = Array.from(ysel.selectedOptions).map(o=>o.value);
    const traces = [];
    const xset = xKey ? getDatasetByKey(xKey) : null;
    yKeys.forEach(yk => {
      const yset = getDatasetByKey(yk);
      if (!yset) return;
      const xarr = xset ? xset.array : yset.array.map((_,i)=>i);
      traces.push({ x: xarr, y: yset.array, name: `${yset.filename}:${yset.name}` });
    });
    Plotly.newPlot(id, traces, {margin:{t:30}});
  }

  xsel.addEventListener('change', updatePlot);
  ysel.addEventListener('change', updatePlot);

  container.querySelector('.add-y').addEventListener('click', ()=>{
    // show a popup selector for a single y
    const sel = makeSelect(buildOptions(), false);
    const dialog = document.createElement('div');
    dialog.className = 'tmp-dialog';
    const btn = document.createElement('button'); btn.textContent='Add';
    const cancel = document.createElement('button'); cancel.textContent='Cancel';
    dialog.appendChild(sel); dialog.appendChild(btn); dialog.appendChild(cancel);
    document.body.appendChild(dialog);
    btn.addEventListener('click', ()=>{
      const key = sel.value;
      const opt = document.createElement('option');
      opt.value = key; opt.textContent = sel.selectedOptions[0].textContent; opt.selected = true;
      ysel.appendChild(opt);
      dialog.remove();
      updatePlot();
    });
    cancel.addEventListener('click', ()=>{ dialog.remove(); });
  });

  container.querySelector('.remove-plot').addEventListener('click', ()=>{
    container.remove();
  });

  // initial plot
  updatePlot();
}

async function init() {
  await fetchFull();
  // Add first plot
  addPlot();
  document.getElementById('add-plot').addEventListener('click', addPlot);
}

window.addEventListener('DOMContentLoaded', init);

/* =========================================================
   抖音旅行图鉴 · 插画信息画布版
   ========================================================= */
const $  = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

function esc(s){
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}
function toast(msg, kind=''){
  const t = $('#toast'); if(!t) return;
  t.textContent = msg; t.className = 'toast show '+kind;
  setTimeout(() => t.className = 'toast '+kind, 2600);
}

const TYPE_EMOJI = {
  '景点':'🏞','景区':'🏞','公园':'🌳','自然':'🌳',
  '美食':'🍜','餐饮':'🍜','吃':'🍜',
  '购物':'🛍','商场':'🛍',
  '住宿':'🏨','酒店':'🏨',
  '交通':'🚆','交通节点':'🚆',
  '夜景':'🌃','夜生活':'🌃',
  '文化':'🏯','寺庙':'🏯',
  '休闲':'☕','体验':'🎢',
};
function emojiFor(stop){
  const t = (stop.type || '').toString();
  for(const k of Object.keys(TYPE_EMOJI)){
    if(t.includes(k)) return TYPE_EMOJI[k];
  }
  if((stop.recommended_foods||[]).length) return '🍜';
  return stop.emoji || '📍';
}

/* ---------- 文件 ---------- */
const MAX_FILES = 5;
let pickedFiles = [];  // [{file: File, path: ""}]
let fileInput, fileEmpty, filePicked;
let currentPlan = null;
const memoryState = { memories: [], selectedIds: new Set(), lastContext: '', lastMatches: [] };
const postTripState = { records: [], photos: [], activeRecord: null };

function bindFile(){
  fileInput = $('#video');
  fileEmpty = $('#fileEmpty');
  filePicked = $('#filePicked');
  const drop = $('#fileDrop');

  function renderList(){
    if(!pickedFiles.length){
      fileEmpty.style.display = '';
      filePicked.style.display = 'none';
      return;
    }
    fileEmpty.style.display = 'none';
    filePicked.style.display = 'block';
    const listEl = $('#filePickedList');
    listEl.innerHTML = pickedFiles.map((p, i) => {
      const mb = (p.file.size/1024/1024).toFixed(1);
      return `<div class="file-picked-row" data-idx="${i}">
        <span class="name">${esc(p.file.name)}</span>
        <span class="size">${mb} MB</span>
        <button type="button" class="rm" data-rm-idx="${i}" title="移除">×</button>
      </div>`;
    }).join('');
    $('#fileCount').textContent = `${pickedFiles.length} / ${MAX_FILES}`;
    listEl.querySelectorAll('.rm').forEach(b => b.addEventListener('click', e => {
      e.preventDefault(); e.stopPropagation();
      const idx = +b.dataset.rmIdx;
      pickedFiles.splice(idx, 1);
      renderList();
    }));
  }

  function addFiles(fileList){
    const remain = MAX_FILES - pickedFiles.length;
    if(remain <= 0){
      toast(`最多 ${MAX_FILES} 个视频`, 'err');
      return;
    }
    [...fileList].slice(0, remain).forEach(f => {
      if(!f.type.startsWith('video/')) return;
      pickedFiles.push({file: f, path: ''});
    });
    renderList();
  }

  fileInput?.addEventListener('change', () => {
    if(fileInput.files?.length){
      addFiles(fileInput.files);
      // 清掉 input 让用户能再次选同名文件
      try{ fileInput.value = ''; }catch{}
    }
  });
  drop?.addEventListener('dragover', e => {
    e.preventDefault(); drop.classList.add('drag-over');
  });
  drop?.addEventListener('dragleave', () => drop.classList.remove('drag-over'));
  drop?.addEventListener('drop', e => {
    e.preventDefault(); drop.classList.remove('drag-over');
    if(e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  });

  $('#fileAdd')?.addEventListener('click', e => {
    e.preventDefault(); e.stopPropagation();
    fileInput.click();
  });
  $('#fileClear')?.addEventListener('click', e => {
    e.preventDefault(); e.stopPropagation();
    pickedFiles = [];
    try{ fileInput.value = ''; }catch{}
    renderList();
  });

  renderList();
}

window.getPickedFiles = () => pickedFiles;

/* ---------- 渲染：海报标题 + 元数据 ---------- */
function renderHero(plan){
  const days = plan.days ?? '—';
  const budget = plan.budget_per_day ?? '—';
  const city = plan.city || (plan.title||'—').slice(0,8);
  const style = (plan.travel_style || (plan.summary||{}).travel_style || '—').replace(/型$/,'');
  $('#metaDays').textContent   = days;
  $('#metaBudget').textContent = budget;
  $('#metaCity').textContent   = city;
  $('#metaStyle').textContent  = style;
  $('#passTo') && ($('#passTo').textContent = city);
  // 标题保持 "路线改改鸭" 固定
}

/* ---------- 渲染：每天故事岛 ---------- */
function renderDays(plan){
  const c = $('#daysContainer'); if(!c) return;
  const days = plan.itinerary || [];
  if(!days.length){
    c.innerHTML = '<div class="empty-state"><div class="big">📝</div><div>没有行程数据</div></div>';
    return;
  }
  c.innerHTML = '<div class="day-archipelago">' + days.map(day => {
    const cls = `d${((day.day-1)%5)+1}`;
    const stops = day.stops || [];
    const tc = stops.reduce((s,x) => s + (Number(x.cost)||0), 0);
    const th = stops.reduce((s,x) => s + (Number(x.time_hours)||0), 0);
    return `<div class="day-island ${cls}">
      <div class="day-head">
        <div class="day-num-row">
          <span class="day-num">Day ${day.day}</span>
          <span class="day-num-deco"></span>
        </div>
        <div class="day-theme">${esc(day.theme||'')}</div>
        <div class="day-meta">
          <span>⏱ <b>${th.toFixed(1)}h</b></span>
          <span>💴 <b>¥${tc}</b></span>
          <span>📍 <b>${stops.length}</b> 站</span>
        </div>
      </div>
      ${stops.map((s,i) => renderStop(s,i+1,day.day)).join('')}
    </div>`;
  }).join('') + renderBackup(plan) + '</div>';
}

function renderBackup(plan){
  const list = (plan && plan.backup_list) || [];
  if(!list.length) return '';
  return `<div class="backup-card">
    <div class="backup-head">📦 备选清单 · 时间紧可省略</div>
    ${list.map(b => {
      const place = typeof b === 'string' ? b : (b.place || '');
      const reason = typeof b === 'string' ? '' : (b.reason || '');
      return `<div class="backup-item">
        <span class="backup-place">${esc(place)}</span>
        ${reason ? `<span class="backup-reason">${esc(reason)}</span>` : ''}
      </div>`;
    }).join('')}
  </div>`;
}

function renderStop(stop, idx, dayNum){
  const e = emojiFor(stop);
  const acts = (stop.activities||[]).map(a => `<span class="chip">${esc(a)}</span>`).join('');
  const foods = (stop.recommended_foods||[]).map(f => `<span class="chip food">🍴 ${esc(f)}</span>`).join('');
  const pros = (stop.pros||[]).map(p => `<span class="chip pros">👍 ${esc(p)}</span>`).join('');
  const cons = (stop.cons||[]).map(c => `<span class="chip cons">👎 ${esc(c)}</span>`).join('');
  const sc = stop.scores || stop.score || {};
  const rows = [
    ['风景', sc.scenery],
    ['美食', sc.food],
    ['出片', sc.photo],
    ['人流', sc.crowded ?? sc.crowd],
    ['性价比', sc.value],
  ].filter(([_,v]) => v != null && !Number.isNaN(Number(v)));
  const scoreHtml = rows.length ? `<div class="score-grid">${rows.map(([k,v]) => {
    const pct = Math.max(0, Math.min(100, Number(v)*10));
    return `<div class="score-row"><span class="lbl">${k}</span>
      <span class="bar"><span class="bar-fill" style="width:${pct}%"></span></span>
      <span class="val">${Number(v).toFixed(1)}</span></div>`;
  }).join('')}</div>` : '';
  const avoidCls = (stop.polarity==='avoid' || stop.avoid) ? ' avoid' : '';
  return `<div class="stop-card${avoidCls}" data-day="${dayNum ?? ''}" data-stop-idx="${idx}">
    <div class="stop-head">
      <div class="stop-emoji">${e}<span class="stop-idx">${idx}</span></div>
      <div class="stop-title">${esc(stop.place||'')}</div>
      ${stop.type ? `<span class="stop-type">${esc(stop.type)}</span>` : ''}
    </div>
    <div class="stop-row">
      ${stop.time_hours != null ? `<span>⏱ <b>${stop.time_hours}h</b></span>` : ''}
      ${stop.cost != null ? `<span>💴 <b>¥${stop.cost}</b></span>` : ''}
      ${stop.transport ? `<span>🚇 <b>${esc(stop.transport)}</b></span>` : ''}
    </div>
    ${acts ? `<div class="chip-list">${acts}</div>` : ''}
    ${foods ? `<div class="chip-list">${foods}</div>` : ''}
    ${(pros || cons) ? `<div class="chip-list">${pros}${cons}</div>` : ''}
    ${scoreHtml}
    ${stop.tip ? `<div class="stop-tip">${esc(stop.tip)}</div>` : ''}
  </div>`;
}

/* ---------- 渲染：必去 / 避雷 ---------- */
function fmtDuoItem(x){
  // 既兼容字符串（旧 pipeline）也兼容 {place, reason} 对象（new_logic_agent）
  if(x == null) return '';
  if(typeof x === 'string') return esc(x);
  if(typeof x === 'object'){
    const place  = x.place || x.name || x.title || '';
    const reason = x.reason || x.note || x.tip || '';
    if(place && reason){
      return `<b>${esc(place)}</b><span class="duo-reason"> · ${esc(reason)}</span>`;
    }
    return esc(place || reason) || esc(JSON.stringify(x));
  }
  return esc(String(x));
}

function renderDuo(plan){
  const mg = plan.must_go || [];
  const av = plan.avoid || plan.avoid_list || [];
  $('#mustGoList').innerHTML = mg.length
    ? mg.map(x => `<li>${fmtDuoItem(x)}</li>`).join('')
    : '<li class="empty">暂无</li>';
  $('#avoidList').innerHTML  = av.length
    ? av.map(x => `<li>${fmtDuoItem(x)}</li>`).join('')
    : '<li class="empty">暂无</li>';
  $('#mustCount').textContent = mg.length;
  $('#avoidCount').textContent = av.length;

  // 行程速览（右侧 teal 节点）：每天的主题 + 站点数（旧版面元素，可能不存在）
  const tq = $('#tipQuick');
  if(tq){
    const days = plan.itinerary || [];
    if(days.length){
      tq.innerHTML = days.map(d => {
        const stops = (d.stops||[]).length;
        const theme = esc(d.theme||'');
        return `<div style="margin-bottom:4px;">
          <b style="color:var(--coral-2);">Day ${d.day}</b> · ${theme}
          <span style="color:var(--ink-3);"> · ${stops} 站</span>
        </div>`;
      }).join('');
    }else{
      tq.textContent = '—';
    }
  }
}

/* ---------- 渲染：Tips ---------- */
/* ---------- 渲染：底部视频贡献条 + 总预算 ---------- */
function renderContributions(plan){
  const box = $('#videoContribList');
  if(box){
    const items = plan.video_contributions || plan.material_contributions || [];
    if(!items.length){
      box.innerHTML = `<div class="contrib-item">
        <div class="contrib-top"><span class="contrib-name">等待生成</span><span class="contrib-pct">—</span></div>
        <div class="contrib-bar"><span class="contrib-fill" style="width:0%"></span></div>
        <div class="contrib-note">每个视频对最终攻略地点的命中比例</div>
      </div>`;
    }else{
      box.innerHTML = items.slice(0, 5).map((it, idx) => {
        const name = it.filename || it.name || `视频 ${idx+1}`;
        const pct = Math.max(0, Math.min(100, Number(it.contribution ?? it.value ?? 0)));
        const matched = it.matched_places || it.places || [];
        const note = matched.length ? `命中：${matched.slice(0,3).join('、')}` : '提供路线/地点线索';
        return `<div class="contrib-item" title="${esc(name)} · ${pct}%">
          <div class="contrib-top"><span class="contrib-name">${esc(name)}</span><span class="contrib-pct">${pct}%</span></div>
          <div class="contrib-bar"><span class="contrib-fill" style="width:${pct}%"></span></div>
          <div class="contrib-note">${esc(note)}</div>
        </div>`;
      }).join('');
    }
  }
}

function renderTips(plan){
  const s = plan.summary || {};
  $('#tipsTotal').textContent = `🧾 总预算 · ¥${s.total_cost ?? '—'}  ·  ${s.travel_style || plan.travel_style || '—'}`;
  renderContributions(plan);
}

/* ---------- 旅行记忆 ---------- */
function currentMemoryQuery(){
  return {
    destination: $('#metaCity')?.textContent || '',
    days: parseInt($('#days')?.value, 10) || '',
    people: parseInt($('#people')?.value, 10) || '',
    budget: parseFloat($('#budget')?.value) || '',
    travel_style: $('#travelStyle')?.value || '',
    target_group: $('#targetGroup')?.value || '',
    themes: $$('.theme-chip.on').map(c => c.dataset.theme),
    extra: ($('#extra')?.value || '').trim(),
  };
}

function selectedMemoryIds(){
  return [...(memoryState.selectedIds || new Set())];
}

function memoryRequestPayload(){
  return {
    ...currentMemoryQuery(),
    selected_memory_ids: selectedMemoryIds(),
  };
}

function updateMemorySelection(id, selected){
  if(!id) return;
  if(selected) memoryState.selectedIds.add(id);
  else memoryState.selectedIds.delete(id);
  renderMemoryStatus();
}

function renderMemoryList(){
  const box = $('#memoryList');
  if(!box) return;
  const memories = memoryState.memories || [];
  if(!memories.length){
    box.innerHTML = '<div class="memory-empty">还没有旅行记忆</div>';
    return;
  }
  box.innerHTML = memories.slice(0, 12).map(m => {
    const id = m.id || '';
    const checked = memoryState.selectedIds.has(id) ? ' checked' : '';
    const liked = (m.liked || []).slice(0,3).map(x => `<span class="memory-tag">${esc(x)}</span>`).join('');
    const disliked = (m.disliked || []).slice(0,3).map(x => `<span class="memory-tag bad">${esc(x)}</span>`).join('');
    const date = (m.created_at || '').slice(0,10);
    return `<div class="memory-item">
      <div class="memory-item-title">
        <label class="memory-select-row">
          <input type="checkbox" class="memory-select" data-memory-id="${esc(id)}"${checked}/>
          <span>${esc(m.trip_title || '旅行复盘')}</span>
        </label>
        <span class="memory-item-date">${esc(date)}</span>
      </div>
      <div class="memory-tags">${liked}${disliked}</div>
    </div>`;
  }).join('');
  box.querySelectorAll('.memory-select').forEach(input => {
    input.addEventListener('change', () => updateMemorySelection(input.dataset.memoryId, input.checked));
  });
}

function renderMemoryStatus(plan){
  const status = $('#memoryStatus');
  if(!status) return;
  const summary = (plan && plan.summary) || {};
  const matches = summary.memory_matches || [];
  if(summary.memory_context){
    status.textContent = `本次使用 ${matches.length || 1} 条历史偏好`;
    status.classList.add('active');
    return;
  }
  const enabled = !!$('#useMemory')?.checked;
  if(enabled){
    const selected = selectedMemoryIds().length;
    const count = memoryState.memories?.length || 0;
    if(selected){
      status.textContent = `将使用已选择的 ${selected} 条历史偏好`;
    }else{
      status.textContent = count ? '已开启，请先选择历史偏好' : '已开启，但还没有保存的历史偏好';
    }
    status.classList.toggle('active', !!selected);
  }else{
    status.textContent = '未使用历史偏好';
    status.classList.remove('active');
  }
}

function renderMemoryTrace(plan){
  renderMemoryStatus(plan);
  const trace = $('#memoryPlanTrace');
  if(!trace) return;
  const summary = (plan && plan.summary) || {};
  if(summary.memory_context){
    trace.textContent = summary.memory_context;
  }else{
    trace.textContent = '生成路线后，这里会显示本次使用的历史偏好。';
  }
}

async function loadMemory(){
  try{
    const r = await fetch('/api/memory');
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || '加载失败');
    memoryState.memories = d.memories || [];
    const valid = new Set(memoryState.memories.map(m => m.id).filter(Boolean));
    memoryState.selectedIds = new Set(selectedMemoryIds().filter(id => valid.has(id)));
    renderMemoryList();
    renderMemoryStatus();
  }catch(err){
    const box = $('#memoryList');
    if(box) box.innerHTML = `<div class="memory-empty">记忆加载失败：${esc(err.message)}</div>`;
  }
}

function renderMemoryRetrieve(context, matches){
  memoryState.lastContext = context || '';
  memoryState.lastMatches = matches || [];
  const box = $('#memoryContext');
  if(!box) return;
  if(!context){
    box.textContent = '没有命中的旅行记忆。';
    return;
  }
  const titles = (matches || []).map(m => `《${m.trip_title || '旅行复盘'}》${m.score ? ` ${m.score}` : ''}`).join('、');
  box.textContent = `${titles ? `命中：${titles}\n\n` : ''}${context}`;
}

async function previewMemory(){
  if(!selectedMemoryIds().length){
    renderMemoryRetrieve('', []);
    toast('请先勾选历史偏好', 'err');
    return;
  }
  try{
    const r = await fetch('/api/memory/retrieve', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(memoryRequestPayload())
    });
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || '检索失败');
    renderMemoryRetrieve(d.context, d.matches || []);
    toast(d.context ? '🔎 已检索旅行记忆' : '没有命中的旅行记忆', d.context ? 'ok' : '');
  }catch(err){
    toast('检索失败：'+err.message, 'err');
  }
}

async function saveMemoryReflection(){
  const record = collectPostTripRecord();
  const review = [
    record.title ? `标题：${record.title}` : '',
    record.actual_places.length ? `实际去了：${record.actual_places.join('、')}` : '',
    record.skipped_places.length ? `没去成：${record.skipped_places.join('、')}` : '',
    record.added_places.length ? `新增发现：${record.added_places.join('、')}` : '',
    record.actual_cost ? `实际花费：${record.actual_cost}` : '',
    record.actual_pace ? `实际节奏：${record.actual_pace}` : '',
    record.review_text ? `真实体验：${record.review_text}` : '',
    record.photos.length ? `照片素材：${record.photos.map(p => p.name).join('、')}` : '',
  ].filter(Boolean).join('\n');
  if(!review){ toast('请先写旅行复盘', 'err'); return; }
  const apiKey = $('#apiKey')?.value.trim() || '';
  if(!apiKey){ toast('需要 API Key 才能提炼记忆', 'err'); return; }
  const btn = $('#saveMemory');
  btn.disabled = true; btn.textContent = '🧠 提炼中…';
  try{
    const r = await fetch('/api/memory/reflect', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({review_text: review, api_key: apiKey})
    });
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || '保存失败');
    memoryState.memories = d.memories || [];
    if(d.memory?.id) memoryState.selectedIds.add(d.memory.id);
    renderMemoryList();
    renderMemoryStatus();
    toast('✓ 已保存历史偏好', 'ok');
    await previewMemory();
  }catch(err){
    toast('保存失败：'+err.message, 'err');
  }finally{
    btn.disabled = false; btn.textContent = '🧠 提炼并保存';
  }
}

/* ---------- 旅行后记录 ---------- */
function splitPostTripList(text){
  return String(text || '')
    .split(/[\n,，、;；]+/)
    .map(x => x.trim())
    .filter(Boolean);
}

function renderPostTripPhotos(){
  const box = $('#postPhotoList');
  if(!box) return;
  const photos = postTripState.photos || [];
  if(!photos.length){
    box.innerHTML = '<span class="file-sub">尚未上传照片</span>';
    return;
  }
  box.innerHTML = photos.map(p =>
    `<span class="post-photo-chip" title="${esc(p.name || '')}">${esc(p.name || '照片')}</span>`
  ).join('');
}

function collectPostTripRecord(){
  return {
    title: ($('#postTripTitle')?.value || '').trim(),
    actual_cost: ($('#postActualCost')?.value || '').trim(),
    actual_pace: ($('#postActualPace')?.value || '').trim(),
    actual_places: splitPostTripList($('#postActualPlaces')?.value),
    skipped_places: splitPostTripList($('#postSkippedPlaces')?.value),
    added_places: splitPostTripList($('#postAddedPlaces')?.value),
    review_text: ($('#postReviewText')?.value || '').trim(),
    photos: postTripState.photos || [],
  };
}

function renderPostTripRecords(records){
  const box = $('#postRecordList');
  if(!box) return;
  const items = records || postTripState.records || [];
  if(!items.length){
    box.innerHTML = '<div class="memory-empty">还没有旅行后记录</div>';
    return;
  }
  box.innerHTML = items.slice(0, 8).map(r => {
    const date = (r.created_at || '').slice(0, 10);
    const places = (r.actual_places || []).slice(0, 3).join('、') || '未记录地点';
    const photo = Number(r.photo_count || (r.photos || []).length || 0);
    return `<div class="post-record-item" data-record-id="${esc(r.id || '')}">
      <div class="post-record-title">
        <span>${esc(r.title || '旅行后记录')}</span>
        <span>${esc(date)}</span>
      </div>
      <div class="file-sub">${esc(places)}${photo ? ` · ${photo} 张照片` : ''}</div>
    </div>`;
  }).join('');
}

async function loadPostTripRecords(){
  try{
    const r = await fetch('/api/post-trip/records');
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || '加载失败');
    postTripState.records = d.compact || d.records || [];
    renderPostTripRecords(postTripState.records);
  }catch(err){
    const box = $('#postRecordList');
    if(box) box.innerHTML = `<div class="memory-empty">旅行记录加载失败：${esc(err.message)}</div>`;
  }
}

function fillActualFromPlan(){
  const plan = currentPlan || {};
  const places = [];
  (plan.itinerary || []).forEach(day => {
    (day.stops || []).forEach(stop => {
      const name = (stop.place || '').trim();
      if(name && !places.includes(name)) places.push(name);
    });
  });
  if(!places.length){
    toast('当前还没有可填入的计划地点', 'err');
    return;
  }
  $('#postActualPlaces').value = places.join('\n');
  if(!($('#postTripTitle')?.value || '').trim()){
    $('#postTripTitle').value = `${plan.title || plan.city || '旅行'}真实复盘`;
  }
  toast('已填入当前计划地点', 'ok');
}

async function uploadPostTripPhotos(files){
  const selected = [...(files || [])].filter(f => f.type?.startsWith('image/')).slice(0, 12);
  if(!selected.length) return;
  const fd = new FormData();
  selected.forEach(f => fd.append('photos', f, f.name));
  const r = await fetch('/api/post-trip/photos', { method:'POST', body: fd });
  const d = await r.json();
  if(!d.ok) throw new Error(d.error || '照片上传失败');
  postTripState.photos = [...(postTripState.photos || []), ...(d.photos || [])];
  renderPostTripPhotos();
  toast(`已上传 ${d.photos?.length || 0} 张旅行照片`, 'ok');
}

async function savePostTripRecord(){
  const record = collectPostTripRecord();
  if(!record.review_text && !record.actual_places.length && !record.photos.length){
    toast('请先记录实际行程、照片或真实体验', 'err');
    return;
  }
  const btn = $('#savePostTripRecord');
  if(btn){ btn.disabled = true; btn.textContent = '保存中…'; }
  try{
    const r = await fetch('/api/post-trip/records', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(record)
    });
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || '保存失败');
    postTripState.activeRecord = d.record;
    postTripState.records = d.compact || d.records || [];
    renderPostTripRecords(postTripState.records);
    toast('✓ 已保存旅行后记录', 'ok');
  }catch(err){
    toast('保存失败：'+err.message, 'err');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '保存旅行记录'; }
  }
}

function bindPostTrip(){
  renderPostTripPhotos();
  $('#fillActualFromPlan')?.addEventListener('click', fillActualFromPlan);
  $('#savePostTripRecord')?.addEventListener('click', savePostTripRecord);
  $('#postTripPhotos')?.addEventListener('change', async e => {
    try{
      await uploadPostTripPhotos(e.target.files || []);
      try{ e.target.value = ''; }catch{}
    }catch(err){
      toast('照片上传失败：'+err.message, 'err');
    }
  });
}

/* ---------- 渲染：原始素材 ---------- */
function renderArchive(data){
  $('#archMarkdown').textContent   = data.markdown_text || '';
  $('#archJson').textContent       = JSON.stringify(data.plan || {}, null, 2);
  $('#archTranscript').textContent = data.transcript_text || '';
  $('#archOcr').textContent        = (data.ocr_lines||[]).join('\n');
  $('#archFused').textContent      = data.fused_text || '';
  const box = $('#archFrames'); box.innerHTML='';
  (data.frames||[]).forEach(url => {
    const img = new Image(); img.loading='lazy'; img.src=url; box.appendChild(img);
  });
}

const DAY_COLORS = ["#F08A6A", "#3FA6E0", "#7CB05A", "#F5C84B",
                    "#9C7BD9", "#4FB3A9", "#E48AAB"];

function renderDayLegend(plan){
  const box = $('#dayLegend');
  if(!box) return;
  const days = plan.itinerary || [];
  if(!days.length){ box.innerHTML = ''; return; }
  box.innerHTML = days.map(d => {
    const color = DAY_COLORS[((d.day-1) % DAY_COLORS.length)];
    return `<button class="lg-pill" data-day="${d.day}">
      <i class="lg-dot" style="background:${color};"></i>第${d.day}天
    </button>`;
  }).join('');
  box.querySelectorAll('.lg-pill').forEach(b => b.addEventListener('click', () => {
    const islands = document.querySelectorAll('#daysContainer .day-island');
    const idx = days.findIndex(x => x.day === +b.dataset.day);
    const el = islands[idx];
    if(el){
      el.scrollIntoView({behavior:'smooth', block:'start'});
      const old = el.style.boxShadow;
      el.style.transition = 'box-shadow .35s';
      el.style.boxShadow = '0 0 0 3px #F5C84B, 3px 3px 0 #2B2118';
      setTimeout(() => el.style.boxShadow = old, 900);
    }
  }));
}

// 滚动观察：自动高亮当前可见的 day-island 对应药丸
function setupDayObserver(){
  // 清理旧 observer
  if(window.__dayObs){ window.__dayObs.disconnect(); }
  const islands = [...document.querySelectorAll('#daysContainer .day-island')];
  if(!islands.length) return;
  const pills = [...document.querySelectorAll('.day-legend .lg-pill')];
  const setActive = (idx) => {
    pills.forEach((p, i) => p.classList.toggle('active', i === idx));
  };
  setActive(0); // 默认高亮第一天

  const root = $('#daysContainer');
  const obs = new IntersectionObserver((entries) => {
    // 找可见比例最大的那个
    const visible = entries
      .filter(e => e.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
    if(visible.length){
      const idx = islands.indexOf(visible[0].target);
      if(idx >= 0) setActive(idx);
    }
  }, { root, threshold: [0.2, 0.5, 0.8] });
  islands.forEach(i => obs.observe(i));
  window.__dayObs = obs;
}

function renderAll(data){
  currentPlan = data.plan || null;
  renderHero(data.plan);
  renderDayLegend(data.plan);
  renderDays(data.plan);
  renderDuo(data.plan);
  renderTips(data.plan);
  renderMemoryTrace(data.plan);
  renderArchive(data);
  // 滚动观察必须放在 renderDays 之后（要拿到新的 day-island）
  requestAnimationFrame(setupDayObserver);
}

function showMap(url){ $('#mapFrame').src = url || '/api/map'; }

/* ---------- 启动加载：永远先拿样例 ---------- */
async function tryLoadExisting(){
  try{
    const r = await fetch('/api/load_sample');
    const d = await r.json();
    if(!d.ok || !d.plan){
      // 样例缺失才退到 plan
      const r2 = await fetch('/api/plan');
      const d2 = await r2.json();
      if(!d2.plan) return;
      const plan = d2.plan;
      let md='', tr='', fu='';
      try{ md = await (await fetch('/output/guide.md')).text(); }catch{}
      renderAll({plan, markdown_text: md, transcript_text: tr, ocr_lines:[], fused_text: fu, frames:[]});
      return;
    }
    let md='', tr='', fu='';
    try{ md = await (await fetch('/output/guide.md')).text(); }catch{}
    try{ tr = await (await fetch('/output/transcript.txt')).text(); }catch{}
    try{ fu = await (await fetch('/output/fused.txt')).text(); }catch{}
    renderAll({plan: d.plan, markdown_text: md, transcript_text: tr,
               ocr_lines:[], fused_text: fu, frames:[]});
  }catch{}
}

/* 任务完成后：拉取**当前真实** plan（不要覆盖成样例） */
async function loadCurrentPlan(){
  try{
    const r = await fetch('/api/plan?t='+Date.now());
    const d = await r.json();
    if(!d.plan) return;
    let md='', tr='', fu='';
    const ts = '?t='+Date.now();
    try{ md = await (await fetch('/output/guide.md'+ts)).text(); }catch{}
    try{ tr = await (await fetch('/output/transcript.txt'+ts)).text(); }catch{}
    try{ fu = await (await fetch('/output/fused.txt'+ts)).text(); }catch{}
    renderAll({plan: d.plan, markdown_text: md, transcript_text: tr,
               ocr_lines:[], fused_text: fu, frames:[]});
  }catch{}
}

/* ---------- 会话按钮：保存/示例/上次 ---------- */
async function bindSessionBtns(){
  $('#loadSample')?.addEventListener('click', async () => {
    const r = await fetch('/api/load_sample', {method:'POST'});
    const d = await r.json();
    if(!d.ok){ toast('加载样例失败', 'err'); return; }
    renderAll({plan:d.plan, markdown_text:'',transcript_text:'',ocr_lines:[],fused_text:'',frames:[]});
    showMap('/api/map?t='+Date.now());
    toast('🔄 已重置为长三角样例', 'ok');
  });
  $('#saveCurrent')?.addEventListener('click', async () => {
    const r = await fetch('/api/save_current', {method:'POST'});
    const d = await r.json();
    toast(d.ok ? '💾 已保存，下次可用 📂 打开' : ('保存失败：'+d.error), d.ok?'ok':'err');
  });
  $('#loadSaved')?.addEventListener('click', async () => {
    const r = await fetch('/api/load_saved', {method:'POST'});
    const d = await r.json();
    if(!d.ok){ toast(d.error || '暂无保存的攻略', 'err'); return; }
    renderAll({plan:d.plan, markdown_text:'',transcript_text:'',ocr_lines:[],fused_text:'',frames:[]});
    showMap('/api/map?t='+Date.now());
    toast('📂 已打开上次保存', 'ok');
  });
}

/* ---------- 偏好按钮：直接走 revise，不重传视频 ---------- */
async function applyPreference(){
  const text = $('#extra').value.trim();
  if(!text){ toast('请先在补充偏好中写点什么', 'err'); return; }
  const apiKey = $('#apiKey').value.trim();
  if(!apiKey){ toast('需要 API Key 才能调路线', 'err'); return; }
  if($('#useMemory')?.checked && !selectedMemoryIds().length){
    toast('请先从历史偏好中选择至少 1 条', 'err');
    $('#postMemoryLibrary')?.scrollIntoView({behavior:'smooth', block:'center'});
    return;
  }

  const btn = $('#applyPref');
  btn.disabled = true; btn.textContent = '✏️ 调整中…';
  try{
    const r = await fetch('/api/revise', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        instruction: text,
        api_key: apiKey,
        use_memory: !!$('#useMemory')?.checked,
        selected_memory_ids: selectedMemoryIds(),
      })
    });
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || '调整失败');
    // 重新拉一次完整数据并渲染
    renderAll({plan:d.plan, markdown_text:'',transcript_text:'',ocr_lines:[],fused_text:'',frames:[]});
    showMap('/api/map?t='+Date.now());
    toast('✓ 已按偏好更新路线', 'ok');
  }catch(err){
    toast('失败：'+err.message, 'err');
  }finally{
    btn.disabled = false; btn.textContent = '✍️ 仅按这条偏好调整（不重传视频）';
  }
}

/* ---------- 提交 ---------- */
async function onSubmit(e){
  e.preventDefault();
  const files = (window.getPickedFiles?.() || []).map(p => p.file);
  if(!files.length){ toast('请先选择至少 1 个视频文件', 'err'); return; }
  const apiKey = $('#apiKey').value.trim();
  if($('#useMemory')?.checked && !selectedMemoryIds().length){
    toast('请先从历史偏好中选择至少 1 条', 'err');
    $('#postMemoryLibrary')?.scrollIntoView({behavior:'smooth', block:'center'});
    return;
  }

  $('#progStep').textContent = `上传 ${files.length} 个视频…`;
  $('#progress').classList.remove('hidden');
  $('#submitBtn').disabled = true;

  // 依次上传每个文件，拿到服务器路径
  const localPaths = [];
  try{
    for(let i = 0; i < files.length; i++){
      $('#progStep').textContent = `上传中 ${i+1}/${files.length} · ${files[i].name}`;
      const fd = new FormData();
      fd.append('video', files[i], files[i].name);
      const up = await fetch('/api/upload', { method:'POST', body:fd });
      const ud = await up.json();
      if(!ud.ok) throw new Error(ud.error || `第 ${i+1} 个上传失败`);
      localPaths.push(ud.path);
    }
  }catch(err){
    toast('上传失败：'+err.message, 'err');
    $('#submitBtn').disabled = false;
    $('#progress').classList.add('hidden');
    return;
  }

  const params = {
    api_key: apiKey,
    local_videos: localPaths,
    days: parseInt($('#days').value,10) || 2,
    people: parseInt($('#people').value,10) || 2,
    budget: parseFloat($('#budget').value) || 500,
    every_seconds: 2,
    max_frames: 30,
    n_frames: 5,
    travel_style: $('#travelStyle')?.value || '标准型',
    target_group: $('#targetGroup')?.value || '大人',
    themes: $$('.theme-chip.on').map(c => c.dataset.theme),
    extra: ($('#extra')?.value || '').trim(),
    use_memory: !!$('#useMemory')?.checked,
    selected_memory_ids: selectedMemoryIds(),
    geocode: true,
  };

  $('#progStep').textContent = '提交生成任务…';

  try{
    const r = await fetch('/api/generate', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(params)
    });
    const d = await r.json();
    if(!d.ok){
      // 残留任务：提示并提供"终止旧任务后重试"
      if(r.status === 409){
        if(confirm('已有任务运行中。是否终止旧任务后重新提交？')){
          await jobControl('cancel');
          // 等一拍让后端把状态落到 cancelled，再重试
          await new Promise(res => setTimeout(res, 600));
          const r2 = await fetch('/api/generate', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify(params)
          });
          const d2 = await r2.json();
          if(!d2.ok) throw new Error(d2.error || '失败');
          pollJob();
          return;
        }
        $('#submitBtn').disabled = false;
        $('#progress').classList.add('hidden');
        return;
      }
      throw new Error(d.error || '失败');
    }
    pollJob();
  }catch(err){
    toast('提交失败：'+err.message, 'err');
    $('#submitBtn').disabled = false;
    $('#progress').classList.add('hidden');
  }
}

let pollTimer = null;
function pollJob(){
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try{
      const r = await fetch('/api/job');
      const j = await r.json();
      $('#progStep').textContent = j.step || '处理中…';
      // 暂停态：黄底 + 按钮变成 ▶
      const prog = $('#progress');
      const pauseBtn = $('#pauseBtn');
      if(j.status === 'paused' || j.paused){
        prog?.classList.add('paused');
        if(pauseBtn){ pauseBtn.textContent = '▶'; pauseBtn.title = '继续'; pauseBtn.dataset.state = 'paused'; }
      }else{
        prog?.classList.remove('paused');
        if(pauseBtn){ pauseBtn.textContent = '⏸'; pauseBtn.title = '暂停（下一步停止）'; pauseBtn.dataset.state = 'running'; }
      }
      if(j.status === 'done'){
        clearInterval(pollTimer);
        $('#submitBtn').disabled = false;
        $('#progress').classList.add('hidden');
        toast('🎉 旅行图鉴生成完成', 'ok');
        await loadCurrentPlan();
        showMap('/api/map?t='+Date.now());
      }else if(j.status === 'error'){
        clearInterval(pollTimer);
        $('#submitBtn').disabled = false;
        $('#progress').classList.add('hidden');
        toast('失败：'+(j.error||'未知'), 'err');
      }else if(j.status === 'cancelled' || j.status === 'idle'){
        clearInterval(pollTimer);
        $('#submitBtn').disabled = false;
        $('#progress').classList.add('hidden');
        if(j.status === 'cancelled') toast('🛑 任务已终止', '');
      }
    }catch{}
  }, 1500);
}

async function jobControl(action){
  try{
    const r = await fetch('/api/job/control', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action})
    });
    const d = await r.json();
    if(!d.ok){ toast(d.error || '操作失败', 'err'); return false; }
    return true;
  }catch(err){
    toast('操作失败：'+err.message, 'err');
    return false;
  }
}

function bindJobControl(){
  $('#pauseBtn')?.addEventListener('click', async () => {
    const btn = $('#pauseBtn');
    const isPaused = btn.dataset.state === 'paused';
    btn.disabled = true;
    const ok = await jobControl(isPaused ? 'resume' : 'pause');
    btn.disabled = false;
    if(ok && !pollTimer) pollJob();
  });
  $('#cancelBtn')?.addEventListener('click', async () => {
    if(!confirm('确定要终止当前任务吗？')) return;
    const btn = $('#cancelBtn');
    btn.disabled = true;
    await jobControl('cancel');
    btn.disabled = false;
    if(!pollTimer) pollJob();
  });
}

// 启动时若服务端有遗留的 running/paused 任务，恢复进度 UI 并继续轮询
async function checkResidualJob(){
  try{
    const r = await fetch('/api/job');
    const j = await r.json();
    if(j.status === 'running' || j.status === 'paused'){
      $('#progress').classList.remove('hidden');
      $('#submitBtn').disabled = true;
      $('#progStep').textContent = j.step || '处理中…';
      pollJob();
    }
  }catch{}
}

/* ---------- archive tabs + iframe message ---------- */
function bindArchive(){
  const modal = $('#archiveModal');
  $('#openArchive')?.addEventListener('click', () => modal?.classList.remove('hidden'));
  $('#closeArchive')?.addEventListener('click', () => modal?.classList.add('hidden'));
  modal?.addEventListener('click', e => {
    if(e.target === modal) modal.classList.add('hidden');
  });
  $$('.arc-tabs button').forEach(b => b.addEventListener('click', () => {
    $$('.arc-tabs button').forEach(x => x.classList.toggle('active', x === b));
    $$('.pane').forEach(p => p.classList.toggle('active', p.id === 'pane-'+b.dataset.tab));
  }));
  window.addEventListener('message', e => {
    if(e.data?.type === 'open-archive') modal?.classList.remove('hidden');
    if(e.data?.type === 'focus-stop'){
      const day = +e.data.day, idx = +e.data.idx;
      const card = document.querySelector(
        `#daysContainer .stop-card[data-day="${day}"][data-stop-idx="${idx}"]`);
      if(card){
        card.scrollIntoView({behavior:'smooth', block:'center'});
        card.classList.add('flash-stop');
        setTimeout(() => card.classList.remove('flash-stop'), 1500);
      }
    }
  });
  window.addEventListener('keydown', e => {
    if(e.key === 'Escape'){
      modal?.classList.add('hidden');
    }
  });
}

function bindMemory(){
  $('#openMemory')?.addEventListener('click', async () => {
    await loadMemory();
    $('#postMemoryLibrary')?.scrollIntoView({behavior:'smooth', block:'center'});
    $('#postMemoryLibrary')?.classList.add('flash-stop');
    setTimeout(() => $('#postMemoryLibrary')?.classList.remove('flash-stop'), 1200);
  });
  $('#saveMemory')?.addEventListener('click', saveMemoryReflection);
  $('#previewMemory')?.addEventListener('click', previewMemory);
  $('#useMemory')?.addEventListener('change', async () => {
    renderMemoryStatus();
    if($('#useMemory').checked && !memoryState.memories.length){
      await loadMemory();
      renderMemoryStatus();
    }
  });
}

/* ---------- 启动 ---------- */
function bindThemeChips(){
  $$('.theme-chip').forEach(b => b.addEventListener('click', e => {
    e.preventDefault();
    b.classList.toggle('on');
  }));
}

function boot(){
  try{
    bindFile();
    bindThemeChips();
    bindArchive();
    bindMemory();
    bindPostTrip();
    bindSessionBtns();
    bindJobControl();
    $('#uploadForm')?.addEventListener('submit', onSubmit);
    $('#applyPref')?.addEventListener('click', applyPreference);
    tryLoadExisting();
    loadMemory();
    loadPostTripRecords();
    checkResidualJob();

    // 防止 input 自动 scrollIntoView 把 body 顶上去
    document.addEventListener('focusin', e => {
      const el = e.target;
      if(!(el instanceof HTMLElement)) return;
      const scroller = el.closest('.cell-body, .duo-card, .day-archipelago');
      if(scroller){
        setTimeout(() => {
          document.documentElement.scrollTop = 0;
          document.body.scrollTop = 0;
        }, 0);
      }
    });
  }catch(err){
    console.error('boot failed:', err);
    toast('初始化失败：'+err.message, 'err');
  }
}
if(document.readyState === 'loading'){
  document.addEventListener('DOMContentLoaded', boot);
}else{
  boot();
}

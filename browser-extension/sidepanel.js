// 苹果风侧边栏：主页(截图分析+地图) / 设置页(全选项+API配置) / 历史页 + 浅深主题
const API = 'http://127.0.0.1:8200'
const $ = (id) => document.getElementById(id)

const capBtn = $('capture'), reloadBtn = $('reload'), backBtn = $('back')
const navtitle = $('navtitle'), navHistory = $('navHistory'), navSettings = $('navSettings'), themeBtn = $('theme')
const statusEl = $('status'), pbar = $('pbar'), pfill = $('pbarfill')
const errEl = $('error'), emptyBox = $('empty'), shotCard = $('shotcard'), shot = $('shot')
const mapCard = $('mapcard'), resultCard = $('resultcard'), candsBox = $('cands')
const infoCard = $('infocard'), infoBox = $('info'), scrollHome = $('v-home')

let mode = 'visible'   // 由设置页'截图范围'下拉控制
let upmode = 'batch'
let map = null, markers = []
let view = 'home'   // home | settings | history

// ===== 主题（浅/深，持久化）=====
const THEME_KEY = 'sg_theme'
function applyTheme(v) {
  document.documentElement.dataset.theme = v === 'dark' ? 'dark' : 'light'
  localStorage.setItem(THEME_KEY, v)
  syncDropdowns()
}
let theme = localStorage.getItem(THEME_KEY) || 'light'
// 注: 首次 applyTheme 移到下拉初始化之后(避免 DD 的 TDZ 引用错误)

// ===== 视图切换 =====
function go(v) {
  view = v
  $('v-home').classList.toggle('on', v === 'home')
  $('v-settings').classList.toggle('on', v === 'settings')
  $('v-history').classList.toggle('on', v === 'history')
  navtitle.textContent = v === 'settings' ? '设置' : v === 'history' ? '历史记录' : '街景定位'
  backBtn.classList.toggle('hidden', v === 'home')
  themeBtn.classList.toggle('hidden', v !== 'home')
  navHistory.classList.toggle('hidden', v !== 'home')
  navSettings.classList.toggle('hidden', v !== 'home')
  reloadBtn.classList.toggle('hidden', v !== 'home')
  if (v === 'settings') loadConfigs()
  if (v === 'history') loadHistory()
  if (v === 'home' && map) setTimeout(() => map.resize(), 30)
}
backBtn.addEventListener('click', () => go('home'))
navSettings.addEventListener('click', () => go('settings'))
navHistory.addEventListener('click', () => go('history'))
themeBtn.addEventListener('click', () => { theme = theme === 'dark' ? 'light' : 'dark'; applyTheme(theme) })

// ===== 自定义下拉（替代原生 select）=====
const DD = {}   // name -> {value, options}
function setupDropdown(name, onPick) {
  const box = document.querySelector(`.dd[data-dd="${name}"]`)
  const btn = box.querySelector('.dd-btn')
  const menu = box.querySelector('.dd-menu')
  const items = [...menu.querySelectorAll('.dd-item')]
  btn.addEventListener('click', (e) => {
    e.stopPropagation()
    const opening = !menu.classList.contains('show')
    document.querySelectorAll('.dd-menu').forEach((m) => m.classList.remove('show'))
    if (!opening) return
    // fixed 定位到按钮下方（右对齐），避免被容器裁剪
    const r = btn.getBoundingClientRect()
    menu.style.top = (r.bottom + 6) + 'px'
    menu.style.right = Math.max(8, window.innerWidth - r.right) + 'px'
    menu.style.left = 'auto'
    menu.classList.add('show')
  })
  items.forEach((it) => it.addEventListener('click', () => {
    DD[name].value = it.dataset.v
    menu.classList.remove('show')
    syncOne(name)
    onPick && onPick(it.dataset.v)
  }))
  DD[name] = { value: items[0].dataset.v, box, items }
  syncOne(name)
}
function syncOne(name) {
  const d = DD[name]
  const cur = d.items.find((i) => i.dataset.v === d.value) || d.items[0]
  d.box.querySelector('.tx').textContent = cur.textContent.trim()
  d.items.forEach((i) => {
    const on = i.dataset.v === d.value
    i.classList.toggle('on', on)
    if (!i.querySelector('.ck')) { const s = document.createElement('span'); s.className = 'ck'; i.appendChild(s) }
    i.querySelector('.ck').textContent = on ? '✓' : ''
  })
}
function syncDropdowns() { Object.keys(DD).forEach(syncOne) }
document.addEventListener('click', () => document.querySelectorAll('.dd-menu').forEach((m) => m.classList.remove('show')))

// 设置页各下拉（值持久化）
const PKEY = 'sg_prefs_ext'
const savedPrefs = JSON.parse(localStorage.getItem(PKEY) || '{}')
function persist() { localStorage.setItem(PKEY, JSON.stringify({
  scope: DD.scope.value, national: DD.national.value, engine: DD.engine.value })) }

setupDropdown('scope', persist)
setupDropdown('national', persist)
setupDropdown('engine', persist)
setupDropdown('shot', (v) => { mode = v })
setupDropdown('upmode', (v) => { upmode = v; syncUpSeg() })
setupDropdown('theme', (v) => { theme = v; applyTheme(v) })
if (savedPrefs.scope) DD.scope.value = savedPrefs.scope
if (savedPrefs.national) DD.national.value = savedPrefs.national
if (savedPrefs.engine) DD.engine.value = savedPrefs.engine
DD.theme.value = theme
syncDropdowns()
applyTheme(theme)   // DD 已就绪, 此时同步主题+下拉显示

// ===== 状态 =====
function show(el, on) { el.classList.toggle('hidden', !on) }
function setStatus(m) { statusEl.textContent = m || ''; statusEl.classList.toggle('show', !!m) }
function setErr(m) { errEl.textContent = m || ''; errEl.classList.toggle('show', !!m) }
function setBusy(b) { capBtn.disabled = b }
function setProg(p) { pbar.classList.toggle('show', p != null); if (p != null) pfill.style.width = Math.min(100, p) + '%' }

// ===== 截图 =====
// 截图范围由设置页下拉控制（见 setupDropdown('shot')）
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab) throw new Error('无活动标签页')
  if (/^(chrome|edge|about|chrome-extension|moz-extension|devtools):/i.test(tab.url || ''))
    throw new Error('浏览器内部页不允许截图，请切到普通网页')
  return tab
}
async function shotVisible() { const t = await activeTab(); return await chrome.tabs.captureVisibleTab(t.windowId, { format: 'png' }) }
// 截图队列（多张，手动上传）
let queue = []   // [{blob, url}]
function updateUploadBtn() {
  const btn = $('uploadBtn')
  btn.textContent = `上传并分析（${queue.length} 张）`
  btn.disabled = queue.length === 0
  show($('uploadcard'), queue.length > 0)
}
function addToQueue(blob) {
  queue.push({ blob, url: URL.createObjectURL(blob) })
  renderQueue()
  updateUploadBtn()
}
function renderQueue() {
  const box = $('shotcard')
  show(box, queue.length > 0)
  box.innerHTML = queue.map((q, i) => `<div style="position:relative;border-bottom:.5px solid var(--sep)">
    <img src="${q.url}" class="shot" />
    <button class="rm" data-i="${i}" style="position:absolute;top:8px;right:8px;width:26px;height:26px;border-radius:50%;border:none;background:rgba(0,0,0,.55);color:#fff;font-size:14px;cursor:pointer">✕</button>
  </div>`).join('')
  box.querySelectorAll('.rm').forEach((b) => b.addEventListener('click', () => {
    const i = +b.dataset.i
    URL.revokeObjectURL(queue[i].url); queue.splice(i, 1)
    renderQueue(); updateUploadBtn()
  }))
}
async function shotFull() {
  const t = await activeTab()
  const [m] = await chrome.scripting.executeScript({ target: { tabId: t.id }, func: () => ({
    h: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight), v: window.innerHeight, y: window.scrollY }) })
  const { h, v, y } = m.result
  const frames = []; const n = Math.min(Math.ceil(h / v), 8)
  for (let i = 0; i < n; i++) {
    await chrome.scripting.executeScript({ target: { tabId: t.id }, func: (yy) => window.scrollTo(0, yy), args: [i * v] })
    await new Promise((r) => setTimeout(r, 280))
    frames.push(await chrome.tabs.captureVisibleTab(t.windowId, { format: 'png' }))
  }
  await chrome.scripting.executeScript({ target: { tabId: t.id }, func: (yy) => window.scrollTo(0, yy), args: [y] })
  return frames
}
async function shotElement() {
  const t = await activeTab()
  const dataUrl = await chrome.tabs.captureVisibleTab(t.windowId, { format: 'png' })
  const [r] = await chrome.scripting.executeScript({ target: { tabId: t.id }, func: () => new Promise((res) => {
    const p = document.body.style.cursor; document.body.style.cursor = 'crosshair'
    const h = (e) => { e.preventDefault(); e.stopPropagation(); document.body.style.cursor = p
      document.removeEventListener('click', h, true); const b = e.target.getBoundingClientRect()
      res({ x: b.x, y: b.y, w: b.width, h: b.height }) }
    document.addEventListener('click', h, true)
    setTimeout(() => { document.body.style.cursor = p; document.removeEventListener('click', h, true); res(null) }, 10000)
  }) })
  return { dataUrl, box: r.result }
}
function loadImg(u) { return new Promise((r) => { const i = new Image(); i.onload = () => r(i); i.src = u }) }
function blobFrom(u) {
  const [meta, b64] = u.split(','); const mime = (meta.match(/data:(.*?);/) || [])[1] || 'image/png'
  const bin = atob(b64); const a = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i)
  return new Blob([a], { type: mime })
}
async function composeFull(frames) {
  const imgs = await Promise.all(frames.map(loadImg))
  const cv = document.createElement('canvas'); cv.width = imgs[0].width; cv.height = imgs[0].height * imgs.length
  const ctx = cv.getContext('2d'); imgs.forEach((im, i) => ctx.drawImage(im, 0, i * imgs[0].height))
  return await new Promise((r) => cv.toBlob(r, 'image/png'))
}
async function composeElement(dataUrl, box) {
  if (!box) return blobFrom(dataUrl)
  const im = await loadImg(dataUrl); const dpr = window.devicePixelRatio || 1
  const sx = Math.max(0, box.x * dpr), sy = Math.max(0, box.y * dpr)
  const sw = Math.max(1, Math.min(im.width - sx, box.w * dpr)), sh = Math.max(1, Math.min(im.height - sy, box.h * dpr))
  const cv = document.createElement('canvas'); cv.width = sw; cv.height = sh
  cv.getContext('2d').drawImage(im, sx, sy, sw, sh, 0, 0, sw, sh)
  return await new Promise((r) => cv.toBlob(r, 'image/png'))
}

// ===== 分析 =====
async function applyPrefs() {
  try {
    const f = new FormData()
    f.append('local_city_engine', DD.engine.value)
    f.append('national_engine', DD.national.value)
    await fetch(`${API}/api/prefs`, { method: 'POST', body: f })
  } catch { /* 忽略 */ }
}
async function submit(blob) {
  const f = new FormData()
  f.append('file', blob, 'shot.png')
  f.append('mode', 'local')
  f.append('scope', DD.scope.value || 'world')
  const res = await fetch(`${API}/api/analyze`, { method: 'POST', body: f })
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `提交失败 HTTP ${res.status}`) }
  return (await res.json()).task_id
}
async function poll(taskId) {
  const t0 = Date.now()
  while (true) {
    await new Promise((r) => setTimeout(r, 700))
    let t
    try {
      const res = await fetch(`${API}/api/tasks/${taskId}`)
      if (!res.ok) throw new Error(`查询任务失败 HTTP ${res.status}`)
      t = (await res.json()).task
    } catch (e) { if (String(e.message).includes('查询任务失败')) throw e; continue }
    setProg(t.progress || 0); setStatus(t.message || '分析中…')
    if (['succeeded', 'failed'].includes(t.status)) return t
    if (Date.now() - t0 > 120000) throw new Error('分析超时')
  }
}

// ===== 地图 =====
function ensureMap() {
  if (map || typeof maplibregl === 'undefined') return
  const el = $('map')
  if (!el || el.clientWidth === 0) return   // 容器无尺寸 → 不初始化(等可见)
  map = new maplibregl.Map({
    container: 'map',
    style: { version: 8,
      sources: { base: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, maxzoom: 18, attribution: '© Esri' } },
      layers: [{ id: 'base', type: 'raster', source: 'base' }] },
    center: [0, 20], zoom: 1, maxZoom: 16, attributionControl: false, zoomDelta: 0.25, wheelZoomPeriod: 30,
  })
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
}
let lastIds = []      // 最近一次分析的任务 id(串行为多个)
let lastThumbs = []   // 对应缩略图 URL   // 渲染序号: 只画最新一次, 杜绝旧任务的地图点残留/串台
function drawMap(cands) {
  ensureMap()
  if (!map) return
  // 无条件清空旧标记(不依赖 load 状态, 避免 once 不触发导致残留)
  markers.forEach((m) => { try { m.remove() } catch (e) {} }); markers = []
  const pts = (cands || []).filter((c) => Number.isFinite(c.lon) && Number.isFinite(c.lat))
  pts.forEach((c, i) => {
    const el = document.createElement('div')
    el.style.cssText = `width:22px;height:22px;border-radius:50%;background:${i === 0 ? '#007AFF' : '#8E8E93'};color:#fff;font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center;box-shadow:0 1px 4px rgba(0,0,0,.3);cursor:pointer`
    el.textContent = i + 1
    markers.push(new maplibregl.Marker({ element: el }).setLngLat([c.lon, c.lat]).addTo(map))
  })
  if (pts.length) {
    const b = new maplibregl.LngLatBounds()
    pts.forEach((c) => b.extend([c.lon, c.lat]))
    // 地图未就绪时 jumpTo(即时, 不依赖动画/事件); 就绪后 fitBounds
    if (map.loaded()) map.fitBounds(b, { padding: 48, maxZoom: 10, duration: 600 })
    else map.once('load', () => map.fitBounds(b, { padding: 48, maxZoom: 10, duration: 600 }))
  }
}

// ===== 渲染结果 =====
function render(task) {
  const cands = [...(task.candidates || [])].sort((a, b) => b.score - a.score)
  emptyBox.classList.add('hidden')
  if (cands.length) {
    show(mapCard, true)
    // 等两帧确保容器有实际尺寸后再初始化/绘制(0尺寸会导致瓦片与点错位)
    requestAnimationFrame(() => requestAnimationFrame(() => {
      ensureMap()
      if (map) map.resize()
      drawMap(cands)
    }))
  } else { show(mapCard, false) }
  show(resultCard, true)
  candsBox.innerHTML = cands.slice(0, 3).map((c, i) => {
    const city = c.city || c.city_zh || '—'
    const country = c.country_zh || c.country || ''
    const conf = Math.min(100, Math.round((c.score || 0) * 100))
    const hint = (c.accuracy_hint || '').split('（')[0]
    return `<div class="cand" data-i="${i}"><span class="num">${i + 1}</span>
      <span class="info"><span class="city">${city}</span><div class="meta">${country}${hint ? ' · ' + hint : ''} · ${c.lat.toFixed(2)},${c.lon.toFixed(2)}</div></span>
      <span class="conf">${conf}%</span></div>`
  }).join('')
  candsBox.querySelectorAll('.cand').forEach((el) => el.addEventListener('click', () => {
    const c = cands[+el.dataset.i]
    if (map && c) map.flyTo({ center: [c.lon, c.lat], zoom: 9, curve: 1.3, speed: 1.6 })
  }))
  const lines = []
  if (task.scene?.summary) lines.push(`<b>场景</b>：${task.scene.summary}`)
  if (task.scene?.visible_text?.length) lines.push(`<b>可见文字</b>：${task.scene.visible_text.join(' · ').slice(0, 160)}`)
  if (task.scene?.languages?.length) lines.push(`<b>语言</b>：${task.scene.languages.join(' / ')}`)
  if (task.gps) lines.push(`<b>EXIF GPS</b>：${task.gps.lat.toFixed(5)}, ${task.gps.lon.toFixed(5)}`)
  if (task.message) lines.push(`<b>结果</b>：${task.message}`)
  if (lines.length) { show(infoCard, true); infoBox.innerHTML = lines.map((l) => `<div class="meta-line">${l}</div>`).join('') }
}

// ===== 串行多图结果列表 =====
let lastDone = []   // [{id,url,task}]
function renderList(done) {
  lastDone = done
  emptyBox.classList.add('hidden')
  show(mapCard, false); show(infoCard, false)
  show(resultCard, true)
  candsBox.innerHTML = `<div class="res-head grp" style="padding:10px 16px 4px">${done.length} 张分析结果（点选查看）</div>` +
    done.map((d, i) => {
      const c0 = [...(d.task.candidates || [])].sort((a, b) => b.score - a.score)[0]
      const place = c0 ? `${c0.city || c0.city_zh || ''} ${c0.country_zh || c0.country || ''}`.trim() : (d.task.status === 'failed' ? '失败' : '无结果')
      return `<div class="hist" data-i="${i}"><div class="th"><img src="${d.url}"/></div>
        <div class="info"><div class="t1">${place}</div><div class="t2">第 ${i + 1} 张 · ${d.task.status === 'succeeded' ? '已完成' : d.task.status}</div></div>
        <span class="chev">›</span></div>`
    }).join('')
  candsBox.querySelectorAll('.hist').forEach((el) => el.addEventListener('click', () => {
    const d = lastDone[+el.dataset.i]
    if (d) { showListBtn(true); render(d.task) }
  }))
  showListBtn(false)
}
function showListBtn(on) {
  let b = $('backListBtn')
  if (on) {
    if (!b) {
      b = document.createElement('button')
      b.id = 'backListBtn'; b.className = 'btn-primary'
      b.style.marginTop = '12px'; b.textContent = '‹ 返回照片列表'
      b.addEventListener('click', () => { showListBtn(false); renderList(lastDone) })
      $('v-home').appendChild(b)
    }
    b.classList.remove('hidden')
  } else if (b) b.classList.add('hidden')
}

// ===== 历史页 =====
async function loadHistory() {
  const box = $('histList')
  box.innerHTML = '<div class="pad" style="color:var(--text2)">加载中…</div>'
  try {
    const tasks = (await (await fetch(`${API}/api/tasks`)).json()).tasks || []
    if (!tasks.length) { box.innerHTML = '<div class="pad" style="color:var(--text2)">暂无历史记录</div>'; return }
    box.innerHTML = tasks.map((t) => {
      const c0 = (t.candidates || [])[0]
      const place = c0 ? `${c0.city || c0.city_zh || ''} ${c0.country_zh || c0.country || ''}`.trim() : (t.status === 'failed' ? '失败' : '—')
      const th = t.candidates?.[0]?.thumbnail_url ? `<img src="${t.candidates[0].thumbnail_url}"/>` : '🖼'
      return `<div class="hist" data-id="${t.task_id}"><div class="th">${th}</div>
        <div class="info"><div class="t1">${place}</div>
        <div class="t2">${t.filename || ''} · ${t.status}</div></div><span class="chev">›</span></div>`
    }).join('')
    box.querySelectorAll('.hist').forEach((el) => el.addEventListener('click', () => showTaskInHome(el.dataset.id)))
  } catch { box.innerHTML = '<div class="pad" style="color:var(--red)">加载失败（后端未启动？）</div>' }
}
async function showTaskInHome(taskId) {
  go('home')
  try {
    const t = (await (await fetch(`${API}/api/tasks/${taskId}`)).json()).task
    // 清空当前结果后渲染历史任务
    show(mapCard, false); show(resultCard, false); show(infoCard, false); emptyBox.classList.add('hidden')
    show(shotCard, false)
    render(t)
  } catch (e) { setErr('加载失败：' + e.message) }
}

// ===== 设置页：API 配置 =====
async function loadConfigs() {
  const box = $('cfgList'), err = $('cfgErr')
  err.classList.remove('show')
  box.innerHTML = '<div class="row"><span class="lb" style="color:var(--text2)">加载中…</span></div>'
  try {
    const r = await fetch(`${API}/api/llm-configs`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const list = (await r.json()).configs || []
    if (!list.length) { box.innerHTML = '<div class="row"><span class="lb" style="color:var(--text2)">暂无配置，请在下方添加</span></div>'; return }
    box.innerHTML = list.map((c) => `<div class="cfg${c.active ? ' active' : ''}" data-id="${c.id}">
      <div class="info"><div class="t1">${c.name || c.model}${c.active ? '<span class="tag">使用中</span>' : ''}</div>
      <div class="t2">${c.model || ''} · ${c.masked_key || ''}</div></div>
      <button class="btn-sm act" data-act="activate" ${c.active ? 'style="display:none"' : ''}>切换</button>
      <button class="btn-sm danger act" data-act="delete">删除</button></div>`).join('')
    box.querySelectorAll('.act').forEach((b) => b.addEventListener('click', async (e) => {
      e.stopPropagation()
      const id = b.closest('.cfg').dataset.id
      const act = b.dataset.act
      try {
        if (act === 'activate') await fetch(`${API}/api/llm-configs/${id}/activate`, { method: 'POST' })
        else { if (!confirm('删除此配置？')) return; await fetch(`${API}/api/llm-configs/${id}`, { method: 'DELETE' }) }
        loadConfigs()
      } catch (e2) { err.textContent = '操作失败：' + e2.message; err.classList.add('show') }
    }))
  } catch (e) { box.innerHTML = '<div class="row"><span class="lb" style="color:var(--red)">加载失败</span></div>'; err.textContent = e.message; err.classList.add('show') }
}
$('cfgAdd').addEventListener('click', async () => {
  const msg = $('cfgMsg'); msg.classList.remove('show')
  const apiKey = $('cfgKey').value.trim(), baseUrl = $('cfgUrl').value.trim(), model = $('cfgModel').value.trim()
  const name = $('cfgName').value.trim()
  if (!apiKey || !baseUrl || !model) { msg.textContent = '请填写 API 地址、Key、模型名'; msg.classList.add('show'); return }
  try {
    const f = new FormData(); f.append('name', name); f.append('api_key', apiKey); f.append('base_url', baseUrl); f.append('model', model)
    const r = await fetch(`${API}/api/llm-configs`, { method: 'POST', body: f })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`)
    $('cfgKey').value = ''; $('cfgName').value = ''
    msg.textContent = '已保存并启用'; msg.style.color = 'var(--green)'; msg.classList.add('show')
    setTimeout(() => msg.classList.remove('show'), 2500)
    loadConfigs()
  } catch (e) { msg.textContent = '保存失败：' + e.message; msg.style.color = ''; msg.classList.add('show') }
})

// ===== 截图（入队，不自动分析）=====
async function takeShot() {
  setErr(''); capBtn.disabled = true
  try {
    setStatus('截图中…')
    let blob
    if (mode === 'full') { const fr = await shotFull(); setStatus(`拼接 ${fr.length} 屏…`); blob = await composeFull(fr) }
    else if (mode === 'element') {
      setStatus('请点击页面上的目标元素…')
      const { dataUrl, box } = await shotElement()
      if (!box) throw new Error('未选择元素')
      blob = await composeElement(dataUrl, box)
    } else blob = blobFrom(await shotVisible())
    addToQueue(blob)
    setStatus('已加入队列，可继续截图或用下方按钮上传')
    setTimeout(() => setStatus(''), 2500)
  } catch (e) { setStatus(''); setErr('截图失败：' + (e.message || e)) }
  finally { capBtn.disabled = false }
}

// ===== 上传并分析（手动触发）=====
async function run() {
  setErr(''); setBusy(true); setProg(0)
  show(mapCard, false); show(resultCard, false); show(infoCard, false)
  emptyBox.classList.add('hidden')
  try {
    await applyPrefs()
    if (!queue.length) throw new Error('请先截图')
    setStatus('提交中…')
    if (upmode === 'fusion' && queue.length >= 2) {
      // 并行同地: 合并为一个任务
      const f = new FormData()
      queue.slice(0, 3).forEach((q, i) => f.append('files', q.blob, `shot${i}.png`))
      f.append('mode', 'local'); f.append('scope', DD.scope.value || 'world')
      const res = await fetch(`${API}/api/analyze-fusion`, { method: 'POST', body: f })
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `提交失败 HTTP ${res.status}`) }
      const taskId = (await res.json()).task_id
      setStatus('分析中…')
      const t = await poll(taskId)
      setStatus('')
      if (t.status === 'failed') throw new Error(t.error || '分析失败')
      lastIds = [taskId]; lastThumbs = [queue[0]?.url]
      showListBtn(false)
      render(t)
    } else {
      // 串行: 全部提交, 结果汇总为"照片列表"由用户选择
      const jobs = []
      for (const q of queue) jobs.push({ id: await submit(q.blob), url: q.url })
      setStatus(`分析中（${jobs.length} 张）…`)
      const done = []
      for (const j of jobs) {
        const t = await poll(j.id)
        done.push({ ...j, task: t })
        setStatus(`已完成 ${done.length}/${jobs.length}`)
      }
      setStatus('')
      lastIds = done.map((d) => d.id)
      lastThumbs = done.map((d) => d.url)
      if (done.length === 1) {
        showListBtn(false)      // 单张: 直接显示详情, 不出列表
        render(done[0].task)
      } else {
        renderList(done)        // 多张: 列表供选择
      }
    }
    // 队列交给结果列表接管(缩略图 URL 保留), 清空当前队列
    queue = []
    renderQueue(); updateUploadBtn()
    scrollHome.scrollTop = 0
  } catch (e) { setStatus(''); setErr('失败：' + (e.message || e)) }
  finally { setProg(null); setBusy(false) }
}

// 上传模式 seg 事件(见上)
document.querySelectorAll('#upmode button').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('#upmode button').forEach((x) => x.classList.remove('on'))
  b.classList.add('on'); upmode = b.dataset.u
  if (DD.upmode) { DD.upmode.value = upmode; syncOne('upmode') }
}))
function syncUpSeg() {
  document.querySelectorAll('#upmode button').forEach((x) => x.classList.toggle('on', x.dataset.u === upmode))
}
$('uploadBtn').addEventListener('click', run)
capBtn.addEventListener('click', takeShot)
reloadBtn.addEventListener('click', () => {
  show(mapCard, false); show(resultCard, false); show(infoCard, false)
  queue.forEach((q) => URL.revokeObjectURL(q.url)); queue = []
  renderQueue(); updateUploadBtn()
  setErr(''); setStatus(''); emptyBox.classList.remove('hidden')
})

updateUploadBtn()   // 初始化上传按钮状态

// 探活
;(async () => {
  try {
    const r = await fetch(`${API}/api/health`)
    if (!r.ok) throw new Error()
    const h = await r.json()
    setStatus(h.warming_up ? '服务已连接（模型预热中…）' : '服务已连接')
    setTimeout(() => setStatus(''), 3000)
  } catch { setErr('未检测到本地服务。先双击桌面「启动-街景定位.bat」启动后端 8200。') }
})()

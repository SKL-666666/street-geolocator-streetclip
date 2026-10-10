// 侧边栏（苹果风·全功能·内嵌地图）：截图 → 后端分析 → 就地渲染地图/候选/场景
const API = 'http://127.0.0.1:8200'
const $ = (id) => document.getElementById(id)

const capBtn = $('capture'), reloadBtn = $('reload')
const statusEl = $('status'), pbar = $('pbar'), pfill = $('pbarfill'), errEl = $('error')
const emptyBox = $('empty'), shotCard = $('shotcard'), shot = $('shot')
const mapCard = $('mapcard'), resultCard = $('resultcard'), candsBox = $('cands')
const infoCard = $('infocard'), infoBox = $('info'), scroll = $('scroll')

let mode = 'visible'
let map = null, markers = []

function show(el, on) { el.classList.toggle('hidden', !on) }
function setStatus(m) { statusEl.textContent = m || ''; statusEl.classList.toggle('show', !!m) }
function setErr(m) { errEl.textContent = m || ''; errEl.classList.toggle('show', !!m) }
function setBusy(b) { capBtn.disabled = b; reloadBtn.disabled = b }
function setProg(p) { pbar.classList.toggle('show', p != null); if (p != null) pfill.style.width = Math.min(100, p) + '%' }

document.querySelectorAll('#shotmode button').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('#shotmode button').forEach((x) => x.classList.remove('on'))
  b.classList.add('on'); mode = b.dataset.m
}))

// ===== 截图 =====
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab) throw new Error('无活动标签页')
  if (/^(chrome|edge|about|chrome-extension|moz-extension|devtools):/i.test(tab.url || ''))
    throw new Error('浏览器内部页不允许截图，请切到普通网页')
  return tab
}
async function shotVisible() { const t = await activeTab(); return await chrome.tabs.captureVisibleTab(t.windowId, { format: 'png' }) }
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
    f.append('local_city_engine', $('engine').value)
    f.append('national_engine', $('national').value)
    await fetch(`${API}/api/prefs`, { method: 'POST', body: f })
  } catch { /* 忽略 */ }
}
async function submit(blob) {
  const f = new FormData()
  f.append('file', blob, 'shot.png')
  f.append('mode', 'local')
  f.append('scope', $('scope').value || 'world')
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

// ===== 地图（MapLibre + Esri 瓦片，内嵌不跳转）=====
function ensureMap() {
  if (map || typeof maplibregl === 'undefined') return
  map = new maplibregl.Map({
    container: 'map',
    style: {
      version: 8,
      sources: { base: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, maxzoom: 18, attribution: '© Esri' } },
      layers: [{ id: 'base', type: 'raster', source: 'base' }],
    },
    center: [0, 20], zoom: 1, maxZoom: 16, attributionControl: false,
    zoomDelta: 0.25, wheelZoomPeriod: 30,
  })
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
}
function drawMap(cands) {
  ensureMap()
  if (!map) return
  const paint = () => {
    markers.forEach((m) => m.remove()); markers = []
    const pts = cands.map((c, i) => ({ c, i, lon: c.lon, lat: c.lat }))
    pts.forEach(({ c, i, lon, lat }) => {
      const el = document.createElement('div')
      el.style.cssText = `width:22px;height:22px;border-radius:50%;background:${i === 0 ? '#007AFF' : '#8E8E93'};color:#fff;font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center;box-shadow:0 1px 4px rgba(0,0,0,.3);cursor:pointer`
      el.textContent = i + 1
      const mk = new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map)
      markers.push(mk)
    })
    if (pts.length) {
      const b = new maplibregl.LngLatBounds()
      pts.forEach((p) => b.extend([p.lon, p.lat]))
      map.fitBounds(b, { padding: 48, maxZoom: 10, duration: 600 })
    }
  }
  if (map.loaded()) paint(); else map.once('load', paint)
}

// ===== 渲染结果（全部在侧边栏）=====
function render(task) {
  const cands = [...(task.candidates || [])].sort((a, b) => b.score - a.score)
  emptyBox.classList.add('hidden')

  // 地图
  if (cands.length) { show(mapCard, true); setTimeout(() => { map && map.resize(); drawMap(cands) }, 30) }

  // 候选
  show(resultCard, true)
  candsBox.innerHTML = cands.slice(0, 3).map((c, i) => {
    const city = c.city || c.city_zh || '—'
    const country = c.country_zh || c.country || ''
    const conf = Math.min(100, Math.round((c.score || 0) * 100))
    const hint = (c.accuracy_hint || '').split('（')[0]
    return `<div class="cand" data-i="${i}">
      <span class="num">${i + 1}</span>
      <span class="info"><span class="city">${city}</span>
        <div class="meta">${country}${hint ? ' · ' + hint : ''}</div></span>
      <span class="conf">${conf}%</span></div>`
  }).join('')
  candsBox.querySelectorAll('.cand').forEach((el) => el.addEventListener('click', () => {
    const c = cands[+el.dataset.i]
    if (map && c) map.flyTo({ center: [c.lon, c.lat], zoom: 9, curve: 1.3, speed: 1.6 })
  }))

  // 场景/证据信息
  const lines = []
  if (task.scene?.summary) lines.push(`<b>场景</b>：${task.scene.summary}`)
  if (task.scene?.visible_text?.length) lines.push(`<b>可见文字</b>：${task.scene.visible_text.join(' · ').slice(0, 160)}`)
  if (task.scene?.languages?.length) lines.push(`<b>语言</b>：${task.scene.languages.join(' / ')}`)
  if (task.gps) lines.push(`<b>EXIF GPS</b>：${task.gps.lat.toFixed(5)}, ${task.gps.lon.toFixed(5)}`)
  if (task.message) lines.push(`<b>结果</b>：${task.message}`)
  if (lines.length) { show(infoCard, true); infoBox.innerHTML = lines.map((l) => `<div class="meta-line">${l}</div>`).join('') }
}

// ===== 主流程 =====
async function run() {
  setErr(''); setBusy(true); setProg(0)
  show(mapCard, false); show(resultCard, false); show(infoCard, false)
  emptyBox.classList.add('hidden'); shotCard.style.display = 'none'
  try {
    await applyPrefs()
    setStatus('截图中…')
    let blob
    if (mode === 'full') { const fr = await shotFull(); setStatus(`拼接 ${fr.length} 屏…`); blob = await composeFull(fr) }
    else if (mode === 'element') {
      setStatus('请点击页面上的目标元素…')
      const { dataUrl, box } = await shotElement()
      if (!box) throw new Error('未选择元素')
      blob = await composeElement(dataUrl, box)
    } else blob = blobFrom(await shotVisible())

    shot.src = URL.createObjectURL(blob); shotCard.style.display = ''
    setStatus('分析中…')
    const t = await poll(await submit(blob))
    setStatus('')
    if (t.status === 'failed') throw new Error(t.error || '分析失败')
    render(t)
    scroll.scrollTop = 0
  } catch (e) { setStatus(''); setErr('失败：' + (e.message || e)) }
  finally { setProg(null); setBusy(false) }
}

capBtn.addEventListener('click', run)
reloadBtn.addEventListener('click', () => {
  show(mapCard, false); show(resultCard, false); show(infoCard, false)
  shotCard.style.display = 'none'; setErr(''); setStatus(''); emptyBox.classList.remove('hidden')
})

// 初始化探活
;(async () => {
  try {
    const r = await fetch(`${API}/api/health`)
    if (!r.ok) throw new Error()
    const h = await r.json()
    setStatus(h.warming_up ? '服务已连接（模型预热中…）' : '服务已连接')
    setTimeout(() => setStatus(''), 3000)
  } catch { setStatus(''); setErr('未检测到本地服务。先双击桌面「启动-街景定位.bat」启动后端 8200。') }
})()

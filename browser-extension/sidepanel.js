// 侧边栏（独立版）：截图 → 直连后端分析 → 自行渲染结果（不依赖网页，避免任务查询 404）
const API = 'http://127.0.0.1:8200'
const APP = 'http://localhost:5173'   // 仅"在地图查看/纠错"时跳转

const $ = (id) => document.getElementById(id)
const capBtn = $('capture')
const reloadBtn = $('reload')
const statusEl = $('status')
const bar = $('bar')
const barfill = $('barfill')
const errEl = $('error')
const shot = $('shot')
const resultBox = $('result')

let mode = 'visible'
let lastTaskId = ''

const show = (el, on) => el.classList.toggle('hide', !on)
function setStatus(m) { statusEl.textContent = m || ''; show(statusEl, !!m) }
function setError(m) { errEl.textContent = m || ''; errEl.classList.toggle('show', !!m) }
function setBusy(b) { capBtn.disabled = b; reloadBtn.disabled = b }
function setProgress(p) { show(bar, p != null); if (p != null) barfill.style.width = Math.min(100, p) + '%' }

document.querySelectorAll('#shotmode button').forEach((b) => {
  b.addEventListener('click', () => {
    document.querySelectorAll('#shotmode button').forEach((x) => x.classList.remove('on'))
    b.classList.add('on'); mode = b.dataset.m
  })
})

// ---------- 截图 ----------
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab) throw new Error('无活动标签页')
  if (/^(chrome|edge|about|chrome-extension|moz-extension|devtools):/i.test(tab.url || '')) {
    throw new Error('浏览器内部页不允许截图，请切到普通网页')
  }
  return tab
}
async function shotVisible() {
  const t = await activeTab()
  return await chrome.tabs.captureVisibleTab(t.windowId, { format: 'png' })
}
async function shotFull() {
  const t = await activeTab()
  const [m] = await chrome.scripting.executeScript({ target: { tabId: t.id }, func: () => ({
    h: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
    v: window.innerHeight, y: window.scrollY }) })
  const { h, v, y } = m.result
  const frames = []
  const n = Math.min(Math.ceil(h / v), 8)
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

// ---------- 合成 ----------
function loadImg(u) { return new Promise((r) => { const i = new Image(); i.onload = () => r(i); i.src = u }) }
function blobFrom(u) {
  const [meta, b64] = u.split(','); const mime = (meta.match(/data:(.*?);/) || [])[1] || 'image/png'
  const bin = atob(b64); const a = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i)
  return new Blob([a], { type: mime })
}
async function composeFull(frames) {
  const imgs = await Promise.all(frames.map(loadImg))
  const w = imgs[0].width, fh = imgs[0].height
  const cv = document.createElement('canvas'); cv.width = w; cv.height = fh * imgs.length
  const ctx = cv.getContext('2d')
  imgs.forEach((im, i) => ctx.drawImage(im, 0, i * fh))
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

// ---------- 分析 ----------
async function applyEngine() {
  try {
    const f = new FormData(); f.append('local_city_engine', $('engine').value)
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
      if (!res.ok) throw new Error(`查询任务失败 HTTP ${res.status}（后端可能已重启）`)
      t = (await res.json()).task
    } catch (e) {
      if (String(e.message).includes('查询任务失败')) throw e
      continue
    }
    setProgress(t.progress || 0)
    setStatus(t.message || '分析中…')
    if (['succeeded', 'failed'].includes(t.status)) return t
    if (Date.now() - t0 > 120000) throw new Error('分析超时')
  }
}

// ---------- 结果渲染（独立，不用网页）----------
function renderResult(task) {
  show(resultBox, true)
  const cands = [...(task.candidates || [])].sort((a, b) => b.score - a.score).slice(0, 3)
  if (!cands.length) { resultBox.innerHTML = '<div class="res-head">未得到候选地点</div>'; return }
  let html = `<div class="res-head">候选地点（Top ${cands.length}）</div>`
  cands.forEach((c, i) => {
    const city = c.city || c.city_zh || '—'
    const country = c.country_zh || c.country || ''
    const conf = Math.min(100, Math.round((c.score || 0) * 100))
    html += `<div class="cand${i === 0 ? ' top' : ''}">
      <span class="rank">${i + 1}</span>
      <span class="info"><span class="city">${city}</span>
        <div class="country">${country}</div></span>
      <span class="conf">${conf}%</span></div>`
  })
  if (lastTaskId) html += `<a class="maplink" href="${APP}/?task=${lastTaskId}" target="_blank">在地图中查看 / 纠错 →</a>`
  resultBox.innerHTML = html
}

// ---------- 主流程 ----------
async function run() {
  setError(''); show(resultBox, false); show(shot, false); setBusy(true); setProgress(0)
  try {
    await applyEngine()
    setStatus('截图中…')
    let blob
    if (mode === 'full') {
      const frames = await shotFull()
      setStatus(`拼接 ${frames.length} 屏…`)
      blob = await composeFull(frames)
    } else if (mode === 'element') {
      setStatus('请点击页面上的目标元素…')
      const { dataUrl, box } = await shotElement()
      if (!box) throw new Error('未选择元素')
      blob = await composeElement(dataUrl, box)
    } else {
      blob = blobFrom(await shotVisible())
    }
    shot.src = URL.createObjectURL(blob); show(shot, true)

    setStatus('分析中…')
    const taskId = await submit(blob)
    lastTaskId = taskId
    const t = await poll(taskId)
    setStatus('')
    if (t.status === 'failed') throw new Error(t.error || '分析失败')
    renderResult(t)
  } catch (e) {
    setStatus('')
    setError('失败：' + (e.message || e))
  } finally { setProgress(null); setBusy(false) }
}

capBtn.addEventListener('click', run)
reloadBtn.addEventListener('click', () => {
  show(resultBox, false); show(shot, false); setError(''); setStatus(''); lastTaskId = ''
})

// 初始化：探活
;(async () => {
  try {
    const r = await fetch(`${API}/api/health`)
    if (!r.ok) throw new Error()
    const h = await r.json()
    setStatus(h.warming_up ? '服务已连接（模型预热中…）' : '服务已连接，可截图分析')
    setTimeout(() => setStatus(''), 3500)
  } catch {
    setStatus('未检测到本地服务')
    setError('请先启动本地服务：双击桌面「启动-街景定位.bat」（后端 8200）')
  }
})()

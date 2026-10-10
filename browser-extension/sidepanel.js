// 侧边栏：多模式截图（直接调用 tabs API，不经 background 转发）→ 提交本地后端 → iframe 载入完整界面
const API = 'http://127.0.0.1:8200'
const APP = 'http://localhost:5173'

const $ = (id) => document.getElementById(id)
const capBtn = $('capture')
const reloadBtn = $('reload')
const statusEl = $('status')
const progress = $('progress')
const pfill = $('pfill')
const errEl = $('error')
const frame = $('app-frame')
const placeholder = $('placeholder')

let mode = 'visible'

function setStatus(msg) { statusEl.textContent = msg || ''; statusEl.classList.toggle('show', !!msg) }
function setError(msg) { errEl.textContent = msg || ''; errEl.classList.toggle('show', !!msg) }
function setBusy(b) { capBtn.disabled = b }

document.querySelectorAll('.mode').forEach((el) => {
  el.addEventListener('click', () => {
    document.querySelectorAll('.mode').forEach((m) => m.classList.remove('on'))
    el.classList.add('on')
    mode = el.dataset.mode
  })
})

// ---------- 截图（直接调用，与第一版同路径）----------
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab) throw new Error('无活动标签页')
  if (/^(chrome|edge|about|chrome-extension|moz-extension):/i.test(tab.url || '')) {
    throw new Error('此页面不允许截图（浏览器内部页），请切到普通网页')
  }
  return tab
}

async function captureVisible() {
  const tab = await activeTab()
  return await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' })
}

async function captureFull() {
  const tab = await activeTab()
  const [meta] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => ({
      scrollH: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
      viewH: window.innerHeight, scrollY: window.scrollY,
    }),
  })
  const { scrollH, viewH, scrollY } = meta.result
  const frames = []
  const pages = Math.min(Math.ceil(scrollH / viewH), 8)   // 上限 8 屏
  for (let p = 0; p < pages; p++) {
    const y = p * viewH
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: (yy) => window.scrollTo(0, yy), args: [y] })
    await new Promise((r) => setTimeout(r, 300))
    frames.push({ y, dataUrl: await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' }) })
  }
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: (yy) => window.scrollTo(0, yy), args: [scrollY] })
  return { frames, viewH, dpr: window.devicePixelRatio || 1 }
}

async function captureElement() {
  const tab = await activeTab()
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' })
  const [r] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => new Promise((resolve) => {
      const prev = document.body.style.cursor
      document.body.style.cursor = 'crosshair'
      const onClick = (e) => {
        e.preventDefault(); e.stopPropagation()
        document.body.style.cursor = prev
        document.removeEventListener('click', onClick, true)
        const b = e.target.getBoundingClientRect()
        resolve({ x: b.x, y: b.y, w: b.width, h: b.height })
      }
      document.addEventListener('click', onClick, true)
      setTimeout(() => { document.body.style.cursor = prev; document.removeEventListener('click', onClick, true); resolve(null) }, 10000)
    }),
  })
  return { dataUrl, box: r.result }
}

// ---------- 合成 ----------
function loadImg(u) { return new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.src = u }) }
function blobFrom(u) {
  const [meta, b64] = u.split(',')
  const mime = (meta.match(/data:(.*?);/) || [])[1] || 'image/png'
  const bin = atob(b64); const a = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i)
  return new Blob([a], { type: mime })
}
async function composeFull(frames, viewH, dpr) {
  const imgs = await Promise.all(frames.map((f) => loadImg(f.dataUrl)))
  const w = imgs[0].width, fh = imgs[0].height            // 每屏实际像素高
  const h = Math.min(fh * imgs.length, Math.round(viewH * dpr * imgs.length))
  const cv = document.createElement('canvas'); cv.width = w; cv.height = h
  const ctx = cv.getContext('2d')
  imgs.forEach((im, i) => ctx.drawImage(im, 0, Math.round(i * fh)))
  return await new Promise((res) => cv.toBlob(res, 'image/png'))
}
async function composeElement(dataUrl, box, dpr) {
  if (!box) return blobFrom(dataUrl)
  const im = await loadImg(dataUrl)
  const sx = Math.max(0, box.x * dpr), sy = Math.max(0, box.y * dpr)
  const sw = Math.max(1, Math.min(im.width - sx, box.w * dpr))
  const sh = Math.max(1, Math.min(im.height - sy, box.h * dpr))
  const cv = document.createElement('canvas'); cv.width = sw; cv.height = sh
  cv.getContext('2d').drawImage(im, sx, sy, sw, sh, 0, 0, sw, sh)
  return await new Promise((res) => cv.toBlob(res, 'image/png'))
}

// ---------- 提交 ----------
async function analyzeBlob(blob) {
  const scope = ($('scope') && $('scope').value) || 'world'
  const form = new FormData()
  form.append('file', blob, 'shot.png')
  form.append('mode', 'local'); form.append('scope', scope)
  const res = await fetch(`${API}/api/analyze`, { method: 'POST', body: form })
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`) }
  return (await res.json()).task_id
}
async function poll(taskId) {
  const t0 = Date.now()
  while (true) {
    await new Promise((r) => setTimeout(r, 700))
    let t
    try { t = (await (await fetch(`${API}/api/tasks/${taskId}`)).json()).task } catch { continue }
    pfill.style.width = Math.min(99, t.progress || 0) + '%'
    setStatus(t.message || '分析中…')
    if (['succeeded', 'failed'].includes(t.status)) return t
    if (Date.now() - t0 > 120000) return t
  }
}
function loadApp(taskId) {
  placeholder.classList.add('hidden')
  frame.src = taskId ? `${APP}/?task=${taskId}` : APP
}

async function applyEngine() {
  // 城市引擎是全局偏好：分析前同步到后端（失败不阻塞）
  try {
    const eng = ($('engine') && $('engine').value) || 'clip'
    const form = new FormData(); form.append('local_city_engine', eng)
    await fetch(`${API}/api/prefs`, { method: 'POST', body: form })
  } catch { /* 忽略 */ }
}

async function run() {
  setError(''); setBusy(true)
  await applyEngine()
  progress.classList.add('show'); pfill.style.width = '0%'
  const dpr = window.devicePixelRatio || 1
  try {
    let blob
    if (mode === 'full') {
      setStatus('滚动截图中…')
      const { frames, viewH, dpr: d } = await captureFull()
      setStatus(`拼接 ${frames.length} 屏…`)
      blob = await composeFull(frames, viewH, d)
    } else if (mode === 'element') {
      setStatus('请在页面上点击要分析的元素…')
      const { dataUrl, box } = await captureElement()
      if (!box) throw new Error('未选择元素（超时）')
      blob = await composeElement(dataUrl, box, dpr)
    } else {
      setStatus('截图中…')
      blob = blobFrom(await captureVisible())
    }
    setStatus('提交分析…')
    const taskId = await poll(await analyzeBlob(blob))
    progress.classList.remove('show'); setStatus('')
    loadApp(taskId)
  } catch (e) {
    progress.classList.remove('show'); setStatus('')
    setError('失败：' + (e.message || e) + '（若为截图失败，请确认已授予"所有网站"权限）')
  } finally { setBusy(false) }
}

capBtn.addEventListener('click', run)
reloadBtn.addEventListener('click', () => { frame.src = frame.src })

;(async () => {
  try {
    const r = await fetch(`${API}/api/health`)
    if (!r.ok) throw new Error('bad')
    const h = await r.json()
    setStatus(h.warming_up ? '服务已连接（模型预热中…）' : '服务已连接 ✓')
    setTimeout(() => setStatus(''), 3000)
    loadApp(null)
  } catch {
    placeholder.classList.remove('hidden')
    setError('未检测到本地服务。双击桌面「启动-街景定位.bat」启动后端8200 + 前端5173。')
  }
})()

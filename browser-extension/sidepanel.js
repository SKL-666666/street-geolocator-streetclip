// 侧边栏：多模式截图 → 提交本地后端 → iframe 载入完整界面（地图/候选/纠错）
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

let mode = 'visible'   // visible | full | element

function setStatus(msg) { statusEl.textContent = msg || ''; statusEl.classList.toggle('show', !!msg) }
function setError(msg) { errEl.textContent = msg || ''; errEl.classList.toggle('show', !!msg) }
function setBusy(b) { capBtn.disabled = b }

// 模式切换
document.querySelectorAll('.mode').forEach((el) => {
  el.addEventListener('click', () => {
    document.querySelectorAll('.mode').forEach((m) => m.classList.remove('on'))
    el.classList.add('on')
    mode = el.dataset.mode
  })
})

// ---------- 图片合成（整页拼接 / 元素裁剪）----------
function loadImg(dataUrl) {
  return new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.src = dataUrl })
}

async function composeFull(frames, viewH) {
  const imgs = await Promise.all(frames.map((f) => loadImg(f.dataUrl)))
  const w = imgs[0].width
  const h = Math.min(viewH * (frames.length - 1) + imgs[imgs.length - 1].height, viewH * frames.length)
  const cv = document.createElement('canvas'); cv.width = w; cv.height = h
  const ctx = cv.getContext('2d')
  for (let i = 0; i < imgs.length; i++) {
    const y = Math.min(frames[i].y, h - imgs[i].height)
    if (y >= 0 && y < h) ctx.drawImage(imgs[i], 0, Math.max(0, y))
  }
  return await new Promise((res) => cv.toBlob(res, 'image/png'))
}

async function composeElement(dataUrl, box) {
  const im = await loadImg(dataUrl)
  // box 是元素在可见区的坐标；captureVisibleTab 输出为物理像素，需按比例缩放
  const scale = im.width / window.innerWidth  // 侧边栏 window 尺寸≠被截页，用 devicePixelRatio 近似
  const dpr = window.devicePixelRatio || 1
  const sx = Math.max(0, box.x * dpr), sy = Math.max(0, box.y * dpr)
  const sw = Math.min(im.width - sx, box.w * dpr), sh = Math.min(im.height - sy, box.h * dpr)
  if (sw <= 0 || sh <= 0) return blobFrom(dataUrl)
  const cv = document.createElement('canvas'); cv.width = sw; cv.height = sh
  cv.getContext('2d').drawImage(im, sx, sy, sw, sh, 0, 0, sw, sh)
  return await new Promise((res) => cv.toBlob(res, 'image/png'))
}

function blobFrom(dataUrl) {
  const [meta, b64] = dataUrl.split(',')
  const mime = (meta.match(/data:(.*?);/) || [])[1] || 'image/png'
  const bin = atob(b64); const arr = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
  return new Blob([arr], { type: mime })
}

// ---------- 提交流程 ----------
async function analyzeBlob(blob) {
  const form = new FormData()
  form.append('file', blob, 'shot.png')
  form.append('mode', 'local'); form.append('scope', 'world')
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

async function run() {
  setError(''); setBusy(true)
  progress.classList.add('show'); pfill.style.width = '0%'
  try {
    setStatus('截图…')
    let blob
    if (mode === 'full') {
      const r = await chrome.runtime.sendMessage({ type: 'CAPTURE_FULL' })
      if (!r?.ok) throw new Error(r?.error || '整页截图失败')
      setStatus(`拼接 ${r.frames.length} 屏…`)
      blob = await composeFull(r.frames, r.viewH)
    } else if (mode === 'element') {
      setStatus('请在页面上点击要分析的元素…')
      const r = await chrome.runtime.sendMessage({ type: 'CAPTURE_ELEMENT' })
      if (!r?.ok) throw new Error(r?.error || '元素截图失败')
      setStatus('裁剪…')
      blob = await composeElement(r.dataUrl, r.box)
    } else {
      const r = await chrome.runtime.sendMessage({ type: 'CAPTURE_VISIBLE' })
      if (!r?.ok) throw new Error(r?.error || '截图失败')
      blob = blobFrom(r.dataUrl)
    }
    setStatus('提交分析…')
    const taskId = await poll(await analyzeBlob(blob))
    progress.classList.remove('show'); setStatus('')
    loadApp(taskId)
  } catch (e) {
    progress.classList.remove('show'); setStatus('')
    setError('失败：' + (e.message || e) + '（确认本地服务已启动：后端8200 + 前端5173）')
  } finally { setBusy(false) }
}

capBtn.addEventListener('click', run)
reloadBtn.addEventListener('click', () => { frame.src = frame.src })

// 初始化：探活 + 直接加载完整界面
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

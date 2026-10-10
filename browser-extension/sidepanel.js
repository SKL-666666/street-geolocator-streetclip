// 侧边栏：截图当前页 → 提交本地后端 → iframe 加载完整界面（地图/候选/纠错）直达结果
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

function setStatus(msg) {
  if (msg) { statusEl.textContent = msg; statusEl.classList.add('show') }
  else statusEl.classList.remove('show')
}
function setError(msg) {
  if (msg) { errEl.textContent = msg; errEl.classList.add('show') }
  else errEl.classList.remove('show')
}
function setBusy(b) { capBtn.disabled = b }

// 截图当前活动标签页（需 background 转发，sidepanel 无 tabs.captureVisibleTab 的调用权限上下文）
async function captureVisible() {
  const resp = await chrome.runtime.sendMessage({ type: 'CAPTURE' })
  if (!resp || !resp.ok) throw new Error(resp?.error || '截图失败')
  return resp.dataUrl
}

function dataUrlToBlob(dataUrl) {
  const [meta, b64] = dataUrl.split(',')
  const mime = (meta.match(/data:(.*?);/) || [])[1] || 'image/png'
  const bin = atob(b64)
  const arr = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
  return new Blob([arr], { type: mime })
}

async function analyze(blob) {
  const form = new FormData()
  form.append('file', blob, 'screenshot.png')
  form.append('mode', 'local')
  form.append('scope', 'world')
  const res = await fetch(`${API}/api/analyze`, { method: 'POST', body: form })
  if (!res.ok) {
    const e = await res.json().catch(() => ({}))
    throw new Error(e.detail || `HTTP ${res.status}`)
  }
  return (await res.json()).task_id
}

async function poll(taskId) {
  const t0 = Date.now()
  while (true) {
    await new Promise((r) => setTimeout(r, 800))
    let task
    try {
      const res = await fetch(`${API}/api/tasks/${taskId}`)
      task = (await res.json()).task
    } catch { continue }
    pfill.style.width = Math.min(99, task.progress || 0) + '%'
    setStatus(task.message || '分析中…')
    if (['succeeded', 'failed'].includes(task.status)) return task
    if (Date.now() - t0 > 120000) return task
  }
}

function loadApp(taskId) {
  placeholder.classList.add('hidden')
  frame.src = taskId ? `${APP}/?task=${taskId}` : APP
}

async function run() {
  setError(''); setBusy(true)
  progress.classList.add('show'); pfill.style.width = '0%'
  setStatus('截图…')
  try {
    const dataUrl = await captureVisible()
    setStatus('提交分析…')
    const taskId = await poll(await analyze(dataUrlToBlob(dataUrl)))
    progress.classList.remove('show')
    setStatus('')
    loadApp(taskId)   // iframe 载入完整界面（地图/候选/双击纠错）
  } catch (e) {
    progress.classList.remove('show')
    setStatus('')
    setError('失败：' + (e.message || e) + '（确认本地服务已启动：后端8200 + 前端5173）')
  } finally {
    setBusy(false)
  }
}

capBtn.addEventListener('click', run)
reloadBtn.addEventListener('click', () => {
  frame.src = frame.src   // 重新加载当前界面
})

// 初始化：探活 + 若已有界面则直接显示
;(async () => {
  try {
    const r = await fetch(`${API}/api/health`)
    if (r.ok) {
      const h = await r.json()
      setStatus(h.warming_up ? '本地服务已连接（模型预热中…）' : '本地服务已连接 ✓')
      loadApp(null)   // 直接显示完整界面（无任务）
    } else throw new Error('bad')
  } catch {
    setStatus('')
    placeholder.classList.remove('hidden')
    setError('未检测到本地服务。请先启动：双击桌面「启动-街景定位.bat」，或手动起后端8200 + 前端5173。')
  }
})()

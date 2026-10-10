// 街景定位插件：截图 → 提交本地后端 → 轮询结果 → 展示/跳转
const API = 'http://127.0.0.1:8200'
const APP = 'http://localhost:5173'   // 完整界面（结果页直达 ?task=<id>）

const $ = (id) => document.getElementById(id)
const captureBtn = $('capture')
const fullBtn = $('captureFull')
const openBtn = $('openApp')
const preview = $('preview')
const progress = $('progress')
const pmsg = $('pmsg')
const ppct = $('ppct')
const pfill = $('pfill')
const resultBox = $('result')
const errBox = $('error')
const hint = $('hint')

let lastTaskId = ''

function setError(msg) { errBox.textContent = msg || '' }
function setBusy(b) { captureBtn.disabled = b; fullBtn.disabled = b }

// ---------- 截图 ----------
async function captureVisible() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  // captureVisibleTab 需要窗口，指定 windowId
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' })
  return dataUrl
}

// 整页截图（滚动拼接，简单版：仅捕获可见，标注说明）
async function captureFullFallback() {
  // 简化：整页拼接需多次滚动，此处退化为可见区（避免复杂滚动逻辑出错）
  return captureVisible()
}

function dataUrlToBlob(dataUrl) {
  const [meta, b64] = dataUrl.split(',')
  const mime = (meta.match(/data:(.*?);/) || [])[1] || 'image/png'
  const bin = atob(b64)
  const arr = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
  return new Blob([arr], { type: mime })
}

// ---------- 提交分析 ----------
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

// ---------- 轮询 ----------
async function poll(taskId) {
  const t0 = Date.now()
  while (true) {
    await new Promise((r) => setTimeout(r, 800))
    let task
    try {
      const res = await fetch(`${API}/api/tasks/${taskId}`)
      task = (await res.json()).task
    } catch { continue }
    const pct = Math.min(99, task.progress || 0)
    pfill.style.width = pct + '%'
    ppct.textContent = pct + '%'
    pmsg.textContent = task.message || '分析中…'
    if (['succeeded', 'failed'].includes(task.status)) {
      pfill.style.width = '100%'
      ppct.textContent = '100%'
      return task
    }
    if (Date.now() - t0 > 120000) return task // 兜底 2 分钟
  }
}

function renderResult(task) {
  resultBox.style.display = 'block'
  resultBox.innerHTML = ''
  if (!task.candidates || !task.candidates.length) {
    resultBox.innerHTML = '<div class="hint">未得到候选地点。</div>'
    return
  }
  const sorted = [...task.candidates].sort((a, b) => b.score - a.score)
  sorted.slice(0, 3).forEach((c, i) => {
    const div = document.createElement('div')
    div.className = 'cand' + (i === 0 ? ' top' : '')
    const city = c.city || c.city_zh || '—'
    const country = c.country_zh || c.country || ''
    const pct = Math.min(100, Math.round((c.score || 0) * 100))
    div.innerHTML = `<span class="pct">${pct} 置信</span>
      <div class="c1">${city}</div>
      <div class="c2">${country}</div>`
    resultBox.appendChild(div)
  })
  // 跳转完整界面（含地图/双击纠错）
  const a = document.createElement('a')
  a.className = 'link'
  a.href = `${APP}/?task=${task.task_id}`
  a.target = '_blank'
  a.textContent = '打开地图查看 / 纠错 →'
  resultBox.appendChild(a)
}

// ---------- 主流程 ----------
async function run(captureFn) {
  setError('')
  resultBox.style.display = 'none'
  progress.style.display = 'none'
  preview.style.display = 'none'
  setBusy(true)
  try {
    const dataUrl = await captureFn()
    preview.src = dataUrl
    preview.style.display = 'block'
    progress.style.display = 'block'
    pmsg.textContent = '提交中…'; ppct.textContent = '0%'; pfill.style.width = '0%'

    const blob = dataUrlToBlob(dataUrl)
    const taskId = await analyze(blob)
    lastTaskId = taskId
    const task = await poll(taskId)
    progress.style.display = 'none'
    if (task.status === 'failed') {
      setError('分析失败：' + (task.error || '未知错误'))
    } else {
      renderResult(task)
    }
  } catch (e) {
    progress.style.display = 'none'
    setError('失败：' + (e.message || e) + '（确认本地服务已启动）')
  } finally {
    setBusy(false)
  }
}

captureBtn.addEventListener('click', () => run(captureVisible))
fullBtn.addEventListener('click', () => run(captureFullFallback))
openBtn.addEventListener('click', () => {
  const url = lastTaskId ? `${APP}/?task=${lastTaskId}` : APP
  chrome.tabs.create({ url })
})

// 启动即探活后端
;(async () => {
  try {
    const r = await fetch(`${API}/api/health`, { method: 'GET' })
    if (!r.ok) throw new Error('bad')
    hint.textContent = '本地服务已连接 ✓'
  } catch {
    hint.textContent = '未检测到本地服务（先启动 backend: uvicorn app.main:app --port 8200）'
  }
})()

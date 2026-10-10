// Service worker：侧边栏截图转发（多种模式）+ 点击图标开启侧边栏 + 右键菜单

chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((e) => console.warn('setPanelBehavior 失败:', e))

// ---------- 截图：多种模式 ----------
async function captureVisible() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab) throw new Error('无活动标签页')
  // 若当前是受限页（chrome:// 等）会抛错
  return await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' })
}

// 整页截图：注入脚本滚动逐屏截取，最后由 sidePanel 侧合成（此处回传多帧）
async function captureFullPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab) throw new Error('无活动标签页')
  // 注入采集脚本，返回页面尺寸 + 滚动的截图位置（逐帧由 SW 截）
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => ({
      scrollH: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
      viewH: window.innerHeight,
      scrollY: window.scrollY,
    }),
  })
  const frames = []
  const step = result.viewH
  const total = Math.min(result.scrollH, step * 8) // 上限 8 屏，防超长页卡死
  for (let y = 0; y < total; y += step) {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: (yy) => window.scrollTo(0, yy), args: [y],
    })
    await new Promise((r) => setTimeout(r, 260)) // 等重绘
    frames.push({ y, dataUrl: await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' }) })
  }
  await chrome.scripting.executeScript({
    target: { tabId: tab.id }, func: (yy) => window.scrollTo(0, yy), args: [result.scrollY],
  })
  return { full: true, frames, viewH: result.viewH }
}

// 元素截图：注入选择器逻辑，等用户点击元素后回传其坐标（后续由 sidePanel 裁剪）
async function captureElementMode() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab) throw new Error('无活动标签页')
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => new Promise((resolve) => {
      const prev = document.body.style.cursor
      document.body.style.cursor = 'crosshair'
      const onClick = (e) => {
        e.preventDefault(); e.stopPropagation()
        document.body.style.cursor = prev
        document.removeEventListener('click', onClick, true)
        const el = e.target
        const r = el.getBoundingClientRect()
        resolve({ x: r.x, y: r.y, w: r.width, h: r.height })
      }
      document.addEventListener('click', onClick, true)
      // 3 秒内未选择则取消
      setTimeout(() => {
        document.body.style.cursor = prev
        document.removeEventListener('click', onClick, true)
        resolve(null)
      }, 8000)
    }),
  })
  if (!result) return null
  return result // {x,y,w,h, 页面坐标}
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  ;(async () => {
    try {
      if (msg?.type === 'CAPTURE_VISIBLE') {
        sendResponse({ ok: true, kind: 'single', dataUrl: await captureVisible() })
      } else if (msg?.type === 'CAPTURE_FULL') {
        sendResponse({ ok: true, kind: 'full', ...(await captureFullPage()) })
      } else if (msg?.type === 'CAPTURE_ELEMENT') {
        const box = await captureElementMode()
        if (!box) { sendResponse({ ok: false, error: '未选择元素（超时）' }); return }
        // 截当前可见区，回传元素在可见区中的相对坐标供裁剪
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
        const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' })
        sendResponse({ ok: true, kind: 'element', dataUrl, box })
      } else if (msg?.type === 'CAPTURE_SELECTION') {
        // 当前选中的文本区域（简化为可见区）
        sendResponse({ ok: true, kind: 'single', dataUrl: await captureVisible() })
      } else {
        sendResponse({ ok: false, error: '未知指令' })
      }
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) })
    }
  })()
  return true // 异步响应
})

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'sg-open-panel', title: '用街景定位分析（打开侧边栏）', contexts: ['page', 'image'],
  })
})
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'sg-open-panel' && tab) {
    chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => {})
  }
})

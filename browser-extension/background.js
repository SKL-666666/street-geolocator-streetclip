// Service worker：侧边栏截图转发 + 点击图标开启侧边栏 + 右键菜单

// 点击工具栏图标 → 打开侧边栏（常驻右侧，不消失）
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((e) => console.warn('setPanelBehavior 失败:', e))

// 侧边栏请求截图当前活动标签页（sidePanel 无 captureVisibleTab 上下文，由 SW 执行）
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === 'CAPTURE') {
    ;(async () => {
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
        if (!tab) throw new Error('无活动标签页')
        const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' })
        sendResponse({ ok: true, dataUrl })
      } catch (e) {
        sendResponse({ ok: false, error: String(e?.message || e) })
      }
    })()
    return true // 异步响应
  }
})

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'sg-open-panel',
    title: '用街景定位分析（打开侧边栏）',
    contexts: ['page', 'image'],
  })
})

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'sg-open-panel' && tab) {
    chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => {})
  }
})

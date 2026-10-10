// Service worker：右键菜单截图分析（可选快捷入口）
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'sg-capture',
    title: '用街景定位分析此页面',
    contexts: ['page', 'image'],
  })
})

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'sg-capture') {
    // 打开弹窗（无法直接程序化截图，交用户点按钮；这里打开 popup 所在扩展页）
    chrome.action.openPopup?.().catch(() => {
      // 部分版本不支持 openPopup → 打开完整界面兜底
      chrome.tabs.create({ url: 'http://localhost:5173' })
    })
  }
})

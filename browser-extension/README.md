# 街景定位 浏览器插件

一键截取当前网页图像 → 交给本地 Street Geolocator 推断拍摄地点。

## 安装（Chrome / Edge，开发者模式）

1. 先启动本地后端（默认 `127.0.0.1:8200`）：
   ```bash
   cd backend
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8200
   ```
   （前端完整界面可选：`cd frontend && npm run dev` → http://localhost:5173）

2. 浏览器地址栏输入 `chrome://extensions`（Edge 为 `edge://extensions`）
3. 打开右上角**开发者模式**
4. 点**加载已解压的扩展程序** → 选择本 `browser-extension/` 目录
5. 工具栏出现插件图标，点击即可用

## 使用

- **截取当前页面并分析**：截可见区域 → 自动提交本地后端 → 显示 Top3 候选
- **打开完整界面**：跳转到 http://localhost:5173/?task=<id> 查看地图、双击纠错
- 结果显示置信度（约 0~100%），Top1 高亮

## 说明

- 插件**只与本地 127.0.0.1:8200 通信**，不发送到任何外部服务器
- 截图仅用于本地分析；纠错后（在完整界面双击地图）会作为参考图加入你的本地检索库
- 后端 CORS 已放行 `chrome-extension://` 来源

## 局限

- `整页截图`当前退化为可见区域（完整滚动拼接较复杂，后续可加）
- 需要本地服务运行；未启动时插件会提示

"""打包版入口（PyInstaller）：启动后端并弹出原生窗口（不跳浏览器）。

双击 StreetGeolocator.exe → 弹出应用窗口（Windows 自带 WebView2 内核），
页面即本工具的 Web UI；关闭窗口 → 服务停止。

窗口自适应：初始 1280×820（16:9 基准），min_size 放宽到 400×700
（支持竖屏 9:16 布局，前端已做响应式适配）。
"""
import threading
import time

import uvicorn

# 静态导入（不能用 "app.main:app" 字符串：frozen 环境下 uvicorn 的动态
# 导入找不到 app 包；静态导入同时保证 PyInstaller 收集整个 app 包）
from app.main import app  # noqa: E402

HOST, PORT = "127.0.0.1", 8200


def _serve() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def _open_window() -> None:
    # 等后端就绪再弹窗口（避免白屏）
    import urllib.request

    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=1)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    import webview

    webview.create_window(
        "Street Geolocator", f"http://{HOST}:{PORT}",
        width=1280, height=820, min_size=(400, 700),
    )
    webview.start()


if __name__ == "__main__":
    threading.Thread(target=_serve, daemon=True).start()
    _open_window()

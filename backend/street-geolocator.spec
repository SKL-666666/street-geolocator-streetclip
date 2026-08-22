# -*- mode: python ; coding: utf-8 -*-
"""Street Geolocator (StreetCLIP 版) 打包配置（PyInstaller onedir，原生窗口版）。

产物：dist/StreetGeolocator/StreetGeolocator.exe（双击弹出原生窗口，不跳浏览器）
- 前端静态资源 → _internal/frontend_dist（只读）
- 本地模型权重在用户 %USERPROFILE%\.cache\huggingface（首次运行自动下载）
- 可写数据（任务库/用户 API Key/偏好）→ exe 同目录 data/（首次运行自动创建）
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(r"C:\Users\yifen\Desktop\digital\agent-work\street-geolocator-streetclip")
BACKEND = ROOT / "backend"

# 强制收集 torch/torchvision（CLIP 本地模型依赖，延迟导入静态分析会漏）
torch_datas, torch_binaries, torch_hidden = [], [], []
for _pkg in ("torch", "torchvision"):
    _d, _b, _h = collect_all(_pkg)
    torch_datas += _d
    torch_binaries += _b
    torch_hidden += _h

# pywebview（原生窗口）：需收集整个包（含各平台后端）
web_datas, web_binaries, web_hidden = collect_all("webview")

# open_clip：BPE 词表等数据文件必须收集（否则 exe 启动加载 CLIP 时报
# FileNotFoundError: bpe_simple_vocab_16e6.txt.gz）
openclip_datas = collect_data_files("open_clip")

# peft：LoRA 微调适配层（代码中保留 import，收集以防运行时缺失）
try:
    peft_datas, peft_binaries, peft_hidden = collect_all("peft")
except Exception:  # noqa: BLE001
    peft_datas, peft_binaries, peft_hidden = [], [], []

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend_dist"),
    # StreetCLIP 本地模型权重（1.6GB，local 引擎 _MODEL_DIR 打包版读 _internal/models/streetclip）
    (str(BACKEND / "models" / "streetclip"), "models/streetclip"),
    # CLIP-B/16 城市引擎权重（0.57GB，open_clip local-dir 加载）
    (str(BACKEND / "models" / "clipb16"), "models/clipb16"),
] + openclip_datas + torch_datas + web_datas + peft_datas

# uvicorn 动态加载的模块（hooks 未覆盖时兜底）+ pywebview 后端
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
] + torch_hidden + web_hidden + peft_hidden

a = Analysis(
    ["run_packaged.py"],
    pathex=[str(BACKEND)],
    binaries=torch_binaries + web_binaries + peft_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StreetGeolocator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # 控制台窗口：日志 + 关闭即停止服务
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StreetGeolocator",
)

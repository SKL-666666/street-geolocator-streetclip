# Street Geolocator (StreetCLIP Edition) — 街景图片地理定位工具 / Street-View Image Geolocation Tool

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Vue3](https://img.shields.io/badge/Vue-3-green) ![FastAPI](https://img.shields.io/badge/FastAPI-0.1-orange)

Upload a street-view photo → the app infers the location (country → city) and shows Top-3 candidate locations on a map. Runs on CPU, no GPU required.

上传一张街景/街拍照片 → 应用自动推断拍摄地点（国家 → 城市），在地图上展示 Top-3 候选位置。纯 CPU 运行，无需 GPU。

---

## ✨ 功能 / Features

- **两级定位 / Two-stage geolocation**: 本地 StreetCLIP 判断国家 Top3 → 城市引擎定城市（本地 CLIP-B/16 免费，或云端 LLM 更准）
  - Local StreetCLIP predicts Top-3 countries → city engine decides the city (local CLIP-B/16 free, or cloud LLM for higher accuracy)
- **本地模型优先 / Local-model first**: 国家判断 100% 本地，无 API 成本；只有「云端 LLM 定城市」需要 API Key
  - Country prediction is 100% local (zero API cost); only "cloud LLM city" needs an API key
- **地图展示 / Map display**: Esri 底图（自动降级腾讯/高德），Top-3 候选点 + 点击联动
  - Esri basemap (auto-fallback to Tencent/AMap), Top-3 candidates with click-to-focus
- **Ctrl+V 粘贴 / Paste support**: 直接粘贴剪贴板图片即可分析
- **打包分发 / Packaged app**: PyInstaller 打包，双击 exe 使用，适合分享给朋友
  - PyInstaller package, double-click exe, ready to share

---

## 🚀 快速开始 / Quick Start

### 方式一：打包版（分享给他人）/ Packaged app (for sharing)

构建 / Build:

```bash
cd backend
pip install pyinstaller
cd ..\frontend && npm run build
cd ..\backend
python -m PyInstaller --clean --noconfirm street-geolocator.spec
# 产物：backend\dist\StreetGeolocator\（整个文件夹发给对方）
# Output: backend\dist\StreetGeolocator\ (send the whole folder)
```

对方使用 / For the recipient:

1. 双击 `StreetGeolocator.exe`（无需安装 Python，权重已内置）
2. 首次启动等待约 1 分钟预热（加载本地模型）
3. 城市引擎选「本地 CLIP-B/16」→ 免费无需 Key；选「云端 LLM」→ 在设置页填写自己的智谱 API Key

### 方式二：本地开发 / Local development

**1. 后端 / Backend**

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8200
```

**2. 前端 / Frontend**

```bash
cd frontend
npm install
npm run dev          # 开发模式
npm run build        # 构建到 frontend/dist
```

浏览器访问 / Open: http://127.0.0.1:8200

---

## 🧠 架构 / Architecture

```
┌─────────────────────────────────────────────────────┐
│  Frontend (Vue3 + MapLibre GL)  →  /api/analyze     │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  Backend (FastAPI + Orchestrator)                   │
│  ① 本地 StreetCLIP 判国家 Top3 (local, free)         │
│  ② 城市引擎: 本地 CLIP-B/16 或 云端 LLM (Top3 国家)    │
│  ③ 城市表坐标优先 → LLM 估算坐标校正 → 兜底             │
│  ④ 预热机制: 本地模型加载完成后才开放上传               │
└─────────────────────────────────────────────────────┘
```

- **第一级 / Stage 1**: [StreetCLIP](https://huggingface.co/geolocal/StreetCLIP) 文本匹配判国家 Top3（本地 ViT-L/14@336）
- **第二级 / Stage 2**: 城市引擎可切换 — 本地 [CLIP ViT-B/16](https://github.com/mlfoundations/open_clip) 或云端 LLM（智谱 GLM-4.6V-FlashX）
- **坐标落点 / Coordinate resolution**: 7100 城表优先 → LLM 估算坐标最近城市校正 → 首都兜底

---

## 🔒 隐私与许可 / Privacy & License

### 隐私 / Privacy

- **API Key 绝不入库**: 用户的 LLM API Key 存于本机 `backend/data/`（已被 .gitignore 排除），每人使用自己的 Key
  - API keys are stored locally in `backend/data/` (git-ignored); each user uses their own key
- **无遥测 / No telemetry**: 不上传任何图片或日志到第三方（除用户主动选择的云端 LLM 调用）

### 模型版权声明 / Model Attribution

本项目**复用了以下第三方预训练模型**，其版权归原作者所有。本项目仅调用推理，未重新训练、未修改其权重。若商用请自行核实各模型许可：

This project **reuses the following third-party pretrained models**. All rights belong to their original authors. This project only performs inference — it does not retrain or modify their weights. Please verify each model's license before commercial use:

| 模型 / Model | 来源 / Source | 用途 / Use | 许可 / License |
|---|---|---|---|
| **StreetCLIP**（基于 OpenAI CLIP ViT-L/14@336 骨干） | [geolocal/StreetCLIP](https://huggingface.co/geolocal/StreetCLIP) (HuggingFace) | 第一级国家分类 / Stage-1 country | **CC BY-NC 4.0（非商用）/ non-commercial**；骨干 CLIP 为 MIT |
| **CLIP ViT-B/16** | [OpenAI CLIP](https://github.com/openai/CLIP) via [open_clip](https://github.com/mlfoundations/open_clip) | 第二级城市（本地引擎）/ Stage-2 city (local) | MIT (open_clip) |
| **GLM-4.6V-FlashX** | [智谱 AI / Zhipu AI](https://open.bigmodel.cn) | 云端城市判断（可选）/ cloud city (optional) | 智谱服务条款 / Zhipu ToS |

> 注：调研/试验阶段评估过但**最终产品未使用**的模型（如 GeoCLIP、OSV5M、DINOv2、SigLIP2、MixVPR 等）不在此列，本表仅列最终管线实际调用的模型。
>
> Note: models evaluated during research but **not used in the final product** (e.g. GeoCLIP, OSV5M, DINOv2, SigLIP2, MixVPR) are not listed — this table only covers models actually invoked by the final pipeline.

本项目自身代码采用 **MIT 许可证**（见 `LICENSE`）。The project's own code is MIT licensed (see `LICENSE`).

---

## 📁 目录结构 / Structure

```
backend/
  app/           FastAPI 应用（管线/知识库/LLM 抽象/API）
  models/        （git-ignored）本地模型权重，从 HuggingFace 下载
  data/          （git-ignored）用户 Key/偏好/任务记录
  dist/          （git-ignored）打包产物
frontend/        Vue3 + Vite + MapLibre GL
docs/            文档
```

## ⚠️ 权重获取 / Model Weights

`backend/models/` 被 git-ignored（体积大）。使用前需自行准备：

- `backend/models/streetclip/` — StreetCLIP 权重 + CLIP 配置（tokenizer 等），从 [HuggingFace](https://huggingface.co/geolocal/StreetCLIP) 获取并放入
- `backend/models/clipb16/` — open_clip ViT-B-16 权重（`open_clip_model.safetensors` + `open_clip_config.json`）
- `backend/models_mixvpr/` — **无需下载**：MixVPR 地理先验是调研期功能（方案 5），当前产品流程已停用（`enable_prior=false`），不影响使用
  - Not needed: the MixVPR geographic-prior feature was researched but is disabled in the final pipeline — you can skip this directory.

打包时 spec 会自动收集模型目录进 exe。

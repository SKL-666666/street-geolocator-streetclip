# Street Geolocator — 街景图片地理定位工具

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Vue3](https://img.shields.io/badge/Vue-3-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.1-orange)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

上传一张街景/街拍照片 → 本地模型推断拍摄地点（国家 → 城市）→ 地图展示 Top-3 候选，可双击地图纠错。
**纯 CPU 运行、本地优先、零 API 成本**，同时提供**网页版**与**浏览器侧边栏插件**。

---

## ✨ 核心功能

| 功能 | 说明 |
|---|---|
| **两级定位** | 本地 StreetCLIP 判国家 Top-3 → 该国城市池内判城市 |
| **DINOv2 检索增强** | 189 张参考图库（39 国）检索投票，与 StreetCLIP 分数融合（国家级 +6.7pp） |
| **多图分析** | 串行批量（各自结果）/ 并行同地（2~3 张合并为一个结果） |
| **置信分诊** | 高置信直信本地；低置信可选云端 VLM 复核国家（开关控制） |
| **双击纠错闭环** | 双击地图选正确位置 → 反查真实国家 → 自动加入检索图库（越用越准） |
| **苹果风 UI** | 浅/深双主题、毛玻璃导航、iOS 系统色（网页与插件统一） |
| **浏览器插件** | 侧边栏常驻，三截图模式（可见区域/整页/选择元素），地图内嵌不跳转 |
| **三范围模式** | 全世界 / 除中国大陆 / 中国模式 |

---

## 🚀 快速开始

### 一键启动（推荐）

双击桌面 **`启动-街景定位.bat`**（或项目根 `启动.bat`）：
- 自动清理端口 → 启后端(8200) → 启前端(5173) → 等预热 → 打开网页

### 手动启动

```bash
# 后端（首次预热 40-90s：加载 StreetCLIP / DINOv2）
cd backend
pip install -r requirements.txt      # 首次
python -m uvicorn app.main:app --host 127.0.0.1 --port 8200

# 前端
cd frontend
npm install                          # 首次
npm run dev                          # → http://localhost:5173
```

### 浏览器插件

1. `chrome://extensions` → 打开**开发者模式**
2. **加载已解压的扩展程序** → 选 `browser-extension/` 目录
3. 工具栏点图标 → 右侧**侧边栏常驻**（网页与插件共用同一后端）

> 需 Chrome 114+（侧边栏 API）。桌面 `street-geolocator-插件-v11.zip` 亦可。

---

## 🏗️ 技术架构

```
前端 (Vue3 + Vite + MapLibre)          ← 苹果风 UI，浅/深主题
浏览器插件 (MV3 sidePanel + MapLibre)   ← 侧边栏常驻，独立渲染
        │ POST /api/analyze (或 /analyze-fusion)
        ▼
后端 (FastAPI + asyncio)  backend/app/
  ├─ pipeline/orchestrator.py   主流程（国家分诊/城市/候选/融合）
  ├─ geokb/local_engine.py      StreetCLIP 国家+城市、特征复用、城市文本缓存
  ├─ geokb/geo_lookup.py        坐标→国家（国界多边形）
  ├─ retrieval/dino_geo.py      DINOv2 图库检索（融合证据）
  ├─ retrieval/gallery_add.py   用户纠错图 → 入库（闭环）
  ├─ llm/vlm_country.py         云端 VLM 复核国家（自适应模式，可选）
  └─ api/routes.py              API 端点
```

**核心管线**：
```
图片 → StreetCLIP 编码一次（国家/城市共用）
   ├─(并发) DINOv2 图库检索 → 分数融合（α=0.125）→ 国家 Top3
   ├─ margin 分诊（自适应模式低置信调 VLM 复核）
   └─ StreetCLIP 在该国城市池判城市 → 候选（置信标定 ~40%）
```

**模型**：StreetCLIP (ViT-L/14@336, 地理微调) · DINOv2-large (图库检索) · 小米 MiMo-v2.6-flash (可选 VLM 复核)

---

## 📊 实测指标

| 指标 | 值 | 说明 |
|---|---|---|
| 国家级 Top-1 | **~63%** | 89 张混合测试集（SC 单独 56.2% + DINOv2 融合） |
| 城市级 Top-1 | **~69%** | 32 张端到端（国家→城市链路） |
| 单图耗时 | **6~10s**（热态） | 首次约 14s（含冷启动） |
| 图库规模 | 189 张 / 39 国 | KartaView 采集，覆盖谷歌街景主要区域 |

> 测试集与全部评测脚本见 `bench_compare/`；优化探索与结论见 `docs/`。

---

## 📁 目录结构

```
backend/          FastAPI 后端（管线/知识库/LLM/API）
  app/            应用代码
  data/           本机数据（图库/反馈/缓存/Key，已 git 忽略）
  models/         模型权重（已 git 忽略，需自备）
  scripts/        构建脚本（DINOv2 图库特征等）
frontend/         Vue3 网页版
browser-extension/ 浏览器插件（MV3，含本地 maplibre）
bench_compare/    评测脚本 + 测试集 + 图库
docs/             文档（按时间归档：08初探 / 09调研 / 10优化突破）
```

---

## ⚖️ 许可与隐私

- 项目自身代码 **MIT**
- **API Key 仅存本机** `backend/data/`（已 git 忽略），无遥测
- 第三方模型许可：StreetCLIP 骨干 CLIP 为 MIT，模型卡为 CC BY-NC 4.0（**非商用**）；商用前请自行核实

## 📖 更多文档

- `docs/2026-10优化突破期/交接文档-2026-10-10.md` — 近期重大改动详解
- `docs/2026-10优化突破期/准确率再突破研究-2026-10.md` — 准确率优化全记录（含已证伪路径）
- `docs/2026-09调研期/归档-优化探索全记录.md` — 早期探索结论

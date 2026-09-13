<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { uploadImage, api, savePrefs as savePrefsApi } from '../api'

const emit = defineEmits(['analyzed'])

const files = ref([])
const previews = ref([])
const dragOver = ref(false)
const uploading = ref(false)
const error = ref('')
// 记住用户选择：localStorage 持久化，刷新/返回上传页后不重置
const STORE_KEY = 'sg_prefs'
function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}') } catch { return {} }
}
function savePrefs() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify({
    mode: mode.value, scope: scope.value,
    enableOcr: enableOcr.value, enableBaidu: enableBaidu.value,
  })) } catch { /* 隐私模式忽略 */ }
}
const prefs = loadPrefs()
const mode = ref('local')  // 仅本地模式（本地判国家 + 城市引擎）
const scope = ref(['world', 'no-cn', 'cn'].includes(prefs.scope) ? prefs.scope : 'world')
const enableOcr = ref(prefs.enableOcr ?? false)
const enableBaidu = ref(prefs.enableBaidu ?? false)
const progress = ref({ done: 0, total: 0 })

const canSubmit = computed(() => files.value.length && !uploading.value && !api.warmingUp &&
  !(api.needsSetup && api.localCityEngine === 'llm'))
const modeList = computed(() => Object.entries(api.modes).map(([k, v]) => ({ key: k, ...v })))

async function onCityEngine(e) {
  const v = e.target.value
  api.localCityEngine = v  // 立即反馈
  await savePrefsApi({ localCityEngine: v })
}

function addFiles(list) {
  error.value = ''
  const ok = [...list].filter((f) => f.type.startsWith('image/'))
  if (ok.length !== list.length) error.value = '已忽略非图片文件'
  for (const f of ok) {
    files.value.push(f)
    previews.value.push(URL.createObjectURL(f))
  }
}

// 全局粘贴：在页面任意位置 Ctrl+V 图片（截图/复制图片）直接加入待分析
function onGlobalPaste(e) {
  const items = e.clipboardData?.items || []
  for (const it of items) {
    if (it.type?.startsWith('image/')) {
      const f = it.getAsFile()
      if (f) {
        addFiles([f])
        e.preventDefault()
        break
      }
    }
  }
}

onMounted(() => window.addEventListener('paste', onGlobalPaste))
onUnmounted(() => window.removeEventListener('paste', onGlobalPaste))

function onFileInput(e) {
  if (e.target.files?.length) addFiles(e.target.files)
  e.target.value = ''
}

function removeFile(i) {
  URL.revokeObjectURL(previews.value[i])
  files.value.splice(i, 1)
  previews.value.splice(i, 1)
}

function onDrop(e) {
  dragOver.value = false
  if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files)
}

async function submit() {
  if (!canSubmit.value) return
  uploading.value = true
  error.value = ''
  const ids = []
  progress.value = { done: 0, total: files.value.length }
  try {
    for (const f of files.value) {
      try {
        ids.push(await uploadImage(f, mode.value, scope.value,
      } catch (e) {
        error.value = `${f.name}: ${e.message}`
      }
      progress.value.done++
    }
    if (ids.length) emit('analyzed', ids)
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="upload-wrap">
    <div class="card upload-card">
      <h2>上传街景照片</h2>
      <p class="muted">支持多选，Ctrl+V 直接粘贴图片</p>

      <!-- 模式选择 -->
      <div class="modes">
        <button
          v-for="m in modeList"
          :key="m.key"
          class="mode-card"
          :class="{ active: mode === m.key }"
          @click="mode = m.key; savePrefs()"
        >
          <div class="mode-name">{{ m.label }}</div>
          <div class="mode-desc">{{ m.desc }}</div>
        </button>
      </div>

      <!-- 范围选择（全世界 / 除中国大陆 / 中国模式） -->
      <div class="scopes">
        <button class="scope-card" :class="{ active: scope === 'world' }" @click="scope = 'world'; savePrefs()">
          🌐 全世界
        </button>
        <button class="scope-card" :class="{ active: scope === 'no-cn' }" @click="scope = 'no-cn'; savePrefs()">
          🌏 除中国大陆
        </button>
        <button class="scope-card china" :class="{ active: scope === 'cn' }" @click="scope = 'cn'; savePrefs()">
          🇨🇳 中国模式
        </button>
      </div>
      <div v-if="scope === 'no-cn'" class="scope-note">
        将排除中国大陆候选，且图片中的中文文字不会被作为推理依据。
      </div>
      <div v-if="scope === 'cn'" class="scope-note china-note">
        中国模式：直接用城市模型推断中国城市（更快、更准），跳过国家级步骤。
      </div>

      <!-- 增强选项（用户勾选） -->
      <div class="enhance-toggles">
        <label class="ds-toggle" :class="{ on: enableOcr }">
          <input type="checkbox" v-model="enableOcr" @change="savePrefs()" />
          <span>
            <b>📝 OCR 文字 + 搜索验证</b>
            <small>识别图中文字 → Tavily 搜索验证地名（每张 +3s，有文字时有效）</small>
          </span>
        </label>
          <span>
            <small>原图+翻转+裁剪三路推理取平均（每张推理时间×3，+3~5pp）</small>
          </span>
        </label>
        <label v-if="scope === 'cn'" class="ds-toggle" :class="{ on: enableBaidu }">
          <input type="checkbox" v-model="enableBaidu" @change="savePrefs()" />
          <span>
            <b>🔍 百度识图</b>
            <small>反向搜图识别地标（每张 +15s，对著名地标有效）</small>
          </span>
        </label>
      </div>

      <!-- 本地模式城市引擎 -->
      <div v-if="mode === 'local'" class="city-engine">
        <b>城市判断引擎</b>
        <div class="ce-opts">
          <label :class="{ on: api.localCityEngine === 'clip' }">
            <input type="radio" value="clip" :checked="api.localCityEngine === 'clip'"
                   @change="onCityEngine" />
            <span>本地 CLIP-B/16（免费）</span>
          </label>
          <label :class="{ on: api.localCityEngine === 'llm' }">
            <input type="radio" value="llm" :checked="api.localCityEngine === 'llm'"
                   @change="onCityEngine" />
            <span>云端 LLM 定城市（更准，耗 token）</span>
          </label>
        </div>
        <small class="muted">国家用本地 StreetCLIP（Top3）；此处决定"国家→城市"一级用哪个引擎。</small>
      </div>

      <div
        class="dropzone"
        :class="{ over: dragOver }"
        @dragover.prevent="dragOver = true"
        @dragleave="dragOver = false"
        @drop.prevent="onDrop"
      >
        <input id="file-input" type="file" accept="image/*" multiple hidden @change="onFileInput" />
        <label for="file-input" class="dropzone-inner">
          <template v-if="previews.length">
            <div class="thumbs">
              <div v-for="(p, i) in previews" :key="p + i" class="thumb-wrap">
                <img :src="p" class="thumb" alt="" />
                <button class="thumb-x" @click.prevent="removeFile(i)">✕</button>
              </div>
            </div>
            <div class="muted">已选 {{ files.length }} 张 · 点击或拖拽继续添加</div>
          </template>
          <template v-else>
            <div class="dz-icon">🖼️</div>
            <div>点击选择图片（可多选）、拖拽到此处，或直接 <b>Ctrl+V 粘贴</b></div>
            <div class="muted">JPG / PNG / WebP，每张 ≤ 20MB</div>
          </template>
        </label>
      </div>

      <div class="actions">
        <button class="btn" :disabled="!canSubmit" @click="submit">
          {{ uploading ? `上传中 ${progress.done}/${progress.total}…` : `开始分析${files.length > 1 ? `（${files.length} 张）` : ''}` }}
        </button>
      </div>
      <!-- 预热中：本地模型加载，禁止上传 -->
      <div v-if="api.warmingUp" class="no-key-note">
        ⏳ <b>本地模型预热中</b>（已 {{ Math.round(api.warmupElapsed) }}s），加载完成后即可上传分析…
      </div>
      <!-- 云端 LLM 定城市且未配置 API Key：禁止发送图片 -->
      <div v-if="api.needsSetup && api.localCityEngine === 'llm'" class="no-key-note">
        🚫 <b>云端 LLM 定城市需要 API Key</b>：请先到右上角「⚙️ 设置」填写你自己的 API Key，
        或切换到「本地 CLIP-B/16」城市引擎（免费，无需 Key）。
      </div>
      <div v-if="error" class="error">{{ error }}</div>

      <div v-if="!api.loaded" class="muted" style="margin-top: 12px">
        ⚠️ 后端未连接：请先启动后端（见 README），并确认 LLM 配置。
      </div>
    </div>
  </div>
</template>

<style scoped>
.upload-wrap { display: flex; justify-content: center; }
.upload-card { width: 100%; max-width: 680px; }
.upload-card h2 { margin-bottom: 8px; }

.modes { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 14px 0 4px; }
.mode-card {
  padding: 10px 12px;
  border: 2px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, background 0.15s;
}
.mode-card.active { border-color: #2563eb; background: #eff6ff; }
.mode-name { font-weight: 700; font-size: 14px; margin-bottom: 4px; }
.mode-desc { font-size: 12px; color: #6b7280; line-height: 1.4; }

.scopes { display: flex; gap: 10px; margin: 6px 0 4px; }
.scope-card {
  flex: 1;
  padding: 10px 12px;
  border: 2px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
  transition: border-color 0.15s, background 0.15s;
}
.scope-card.active { border-color: #059669; background: #ecfdf5; }
.scope-card.china.active { border-color: #dc2626; background: #fef2f2; }
.scope-note { font-size: 12px; color: #065f46; background: #ecfdf5; border-radius: 8px; padding: 6px 10px; margin-bottom: 4px; }
.china-note { color: #991b1b; background: #fef2f2; }
.enhance-toggles { display: flex; flex-direction: column; gap: 8px; margin: 10px 0 4px; }

.ds-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 10px 0 4px;
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #f9fafb;
  cursor: pointer;
}
.ds-toggle input { width: 18px; height: 18px; accent-color: #2563eb; flex-shrink: 0; }
.ds-toggle span { display: flex; flex-direction: column; gap: 2px; }
.ds-toggle b { font-size: 13px; }
.ds-toggle small { font-size: 12px; color: #6b7280; }

.city-engine {
  margin: 10px 0 4px;
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #f9fafb;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.city-engine > b { font-size: 13px; }
.city-engine .ce-opts { display: flex; gap: 10px; flex-wrap: wrap; }
.city-engine .ce-opts label {
  display: flex; align-items: center; gap: 6px;
  font-size: 12.5px; padding: 5px 10px; border-radius: 8px;
  border: 1px solid #e5e7eb; background: #fff; cursor: pointer;
}
.city-engine .ce-opts label.on { border-color: #2563eb; background: #eff6ff; }
.city-engine .ce-opts input { accent-color: #2563eb; }
.city-engine small { font-size: 11.5px; color: #6b7280; }

.dropzone {
  margin: 16px 0;
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  overflow: hidden;
  transition: border-color 0.15s, background 0.15s;
}
.dropzone.over { border-color: #2563eb; background: #eff6ff; }
.dropzone-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 16px;
  cursor: pointer;
  text-align: center;
}
.dz-icon { font-size: 40px; }
.thumbs { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.thumb-wrap { position: relative; }
.thumb { width: 96px; height: 72px; object-fit: cover; border-radius: 8px; }
.thumb-x {
  position: absolute; top: -6px; right: -6px;
  width: 20px; height: 20px; border-radius: 50%;
  border: none; background: #dc2626; color: #fff;
  font-size: 11px; cursor: pointer;
}
.actions { display: flex; justify-content: center; }
.no-key-note {
  margin-top: 12px;
  background: #fef2f2; color: #991b1b;
  border: 1px solid #fca5a5; border-radius: 8px;
  padding: 10px 14px; font-size: 13px; text-align: center;
}
.error { margin-top: 12px; color: #dc2626; font-size: 14px; text-align: center; }

/* 竖屏/窄屏适配（16:9 → 9:16） */
@media (max-width: 640px) {
  .modes { grid-template-columns: 1fr; }
  .scopes { flex-wrap: wrap; }
  .scope-card { flex: 1 1 auto; min-width: 120px; }
  .ce-opts { flex-direction: column; }
}
</style>



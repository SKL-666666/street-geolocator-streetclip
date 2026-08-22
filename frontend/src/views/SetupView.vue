<script setup>
import { ref, onMounted } from 'vue'
import { fetchLLMConfigs, addLLMConfig, activateLLMConfig, deleteLLMConfig } from '../api'

const emit = defineEmits(['saved', 'back'])

// ---- 已有配置 ----
const configs = ref([])
const loading = ref(false)
const opError = ref('')

async function refresh() {
  try {
    configs.value = await fetchLLMConfigs()
  } catch (e) {
    opError.value = e.message
  }
}

async function onActivate(cfg) {
  opError.value = ''
  try {
    configs.value = await activateLLMConfig(cfg.id)
    emit('saved')
  } catch (e) {
    opError.value = e.message
  }
}

async function onDelete(cfg) {
  if (!confirm(`删除配置「${cfg.name}」？`)) return
  opError.value = ''
  try {
    configs.value = await deleteLLMConfig(cfg.id)
    emit('saved')
  } catch (e) {
    opError.value = e.message
  }
}

// ---- 添加自定义配置 ----
const name = ref('')
const baseUrl = ref('')
const apiKey = ref('')
const model = ref('')
const saving = ref(false)
const error = ref('')
const notice = ref('')

async function onAdd() {
  if (!apiKey.value.trim()) {
    error.value = '请填写 API Key'
    return
  }
  if (!baseUrl.value.trim()) {
    error.value = '请填写 API 地址（Base URL）'
    return
  }
  if (!model.value.trim()) {
    error.value = '请填写模型名'
    return
  }
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const { configs: list, duplicated } = await addLLMConfig({
      name: name.value.trim() || `${model.value.trim()}`,
      apiKey: apiKey.value.trim(),
      baseUrl: baseUrl.value.trim(),
      model: model.value.trim(),
    })
    configs.value = list
    if (duplicated) {
      notice.value = 'ℹ️ 该配置已存在（相同 Key + 模型 + 地址），已自动切换到它，未重复添加'
    } else {
      apiKey.value = ''
    }
    emit('saved')
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

onMounted(refresh)
</script>

<template>
  <div class="setup-wrap">
    <div class="card setup-card">
      <div class="setup-head">
        <h2>🔑 大模型 API 配置</h2>
        <button class="btn-ghost" @click="emit('back')">← 返回</button>
      </div>

      <!-- 已有配置列表 -->
      <div v-if="configs.length" class="saved-section">
        <div class="section-title">已有配置（{{ configs.length }}）—— 点击一键切换</div>
        <div v-for="c in configs" :key="c.id" class="saved-item" :class="{ active: c.active }">
          <div class="saved-main">
            <div class="saved-name">
              {{ c.active ? '✅' : '🔘' }} {{ c.name }}
              <span v-if="c.active" class="using-tag">使用中</span>
            </div>
            <div class="saved-meta">
              {{ c.model || '默认模型' }} · Key {{ c.masked_key }}
              <span v-if="c.base_url" class="muted"> · {{ c.base_url.replace('https://', '').split('/')[0] }}</span>
              <span v-if="c.created_at" class="muted"> · {{ fmtTime(c.created_at) }}</span>
            </div>
          </div>
          <div class="saved-actions">
            <button v-if="!c.active" class="btn-sm" :disabled="loading" @click="onActivate(c)">切换</button>
            <button class="btn-sm danger" :disabled="loading" @click="onDelete(c)">删除</button>
          </div>
        </div>
      </div>
      <div v-else class="muted hint">还没有已保存的配置，请在下方添加第一个。</div>
      <div v-if="opError" class="error">{{ opError }}</div>

      <hr class="divider" />

      <!-- 添加自定义配置 -->
      <div class="section-title">添加配置（保存后立即使用）</div>
      <p class="muted">OpenAI 兼容接口：地址 / Key / 模型名。Key 只存本机，按平台直接计费。</p>

      <div class="field">
        <label>配置名称（可选，便于区分）</label>
        <input v-model="name" type="text" placeholder="如：我的智谱号 / 备用豆包号（留空自动用模型名）" />
      </div>

      <div class="field">
        <label>API 地址（Base URL）<span class="req">*</span></label>
        <input v-model="baseUrl" type="text" placeholder="如 https://open.bigmodel.cn/api/paas/v4" />
      </div>

      <div class="field">
        <label>API Key <span class="req">*</span></label>
        <input v-model="apiKey" type="password" placeholder="粘贴你的 API Key" autocomplete="off" />
      </div>

      <div class="field">
        <label>模型名 <span class="req">*</span></label>
        <input v-model="model" type="text" placeholder="如 glm-4.6v-flashx / qwen-vl-max（任意视觉模型名）" />
      </div>

      <div class="actions">
        <button class="btn" :disabled="saving" @click="onAdd">
          {{ saving ? '保存中…' : '➕ 保存并添加' }}
        </button>
      </div>
      <div v-if="error" class="error">{{ error }}</div>
      <div v-if="notice" class="notice">{{ notice }}</div>
      <div class="muted hint">
        提示：任意 OpenAI 兼容的视觉模型接口都可用（智谱/通义/豆包/百度/混元/Kimi/
        硅基流动/阶跃/零一/OpenRouter 等），Base URL 与模型名请按各平台文档填写。
      </div>
    </div>
  </div>
</template>

<style scoped>
.setup-wrap { display: flex; justify-content: center; }
.setup-card { width: 100%; max-width: 640px; display: flex; flex-direction: column; gap: 14px; }
.setup-head { display: flex; justify-content: space-between; align-items: center; }
.btn-ghost { background: #e5e7eb; color: #374151; padding: 6px 12px; font-size: 13px; border: none; border-radius: 8px; cursor: pointer; }
.btn-ghost:hover { background: #d1d5db; }

.section-title { font-weight: 700; font-size: 14px; color: #374151; }
.divider { border: none; border-top: 1px dashed #d1d5db; margin: 4px 0; }

.saved-section { display: flex; flex-direction: column; gap: 8px; }
.saved-item {
  display: flex; justify-content: space-between; align-items: center; gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e5e7eb; border-radius: 10px;
  background: #fff;
}
.saved-item.active { border-color: #059669; background: #ecfdf5; }
.saved-name { font-weight: 600; font-size: 14px; }
.using-tag {
  margin-left: 6px; padding: 1px 8px; font-size: 11px;
  background: #059669; color: #fff; border-radius: 999px;
}
.saved-meta { font-size: 12px; color: #6b7280; margin-top: 2px; }
.saved-actions { display: flex; gap: 6px; flex-shrink: 0; }
.btn-sm {
  padding: 5px 12px; font-size: 12px; border: none; border-radius: 6px;
  background: #2563eb; color: #fff; cursor: pointer;
}
.btn-sm:hover { background: #1d4ed8; }
.btn-sm.danger { background: #dc2626; }
.btn-sm.danger:hover { background: #b91c1c; }

.field { display: flex; flex-direction: column; gap: 6px; }
.field label { font-weight: 600; font-size: 13px; }
.req { color: #dc2626; }
.field input {
  padding: 10px 12px; border: 1px solid #d1d5db; border-radius: 8px;
  font-size: 14px; width: 100%; box-sizing: border-box; background: #fff;
}
.field input:focus { outline: 2px solid #2563eb; border-color: transparent; }
.actions { display: flex; justify-content: center; }
.error { color: #dc2626; font-size: 14px; text-align: center; }
.notice { color: #065f46; background: #ecfdf5; border: 1px solid #6ee7b7; border-radius: 8px; padding: 8px 12px; font-size: 13px; text-align: center; }
.hint { font-size: 12px; line-height: 1.7; }
</style>

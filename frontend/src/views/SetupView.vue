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
  if (!apiKey.value.trim()) { error.value = '请填写 API Key'; return }
  if (!baseUrl.value.trim()) { error.value = '请填写 API 地址'; return }
  if (!model.value.trim()) { error.value = '请填写模型名'; return }
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const { configs: list, duplicated } = await addLLMConfig({
      name: name.value.trim() || model.value.trim(),
      apiKey: apiKey.value.trim(),
      baseUrl: baseUrl.value.trim(),
      model: model.value.trim(),
    })
    configs.value = list
    notice.value = duplicated ? '该配置已存在，已切换到它' : '已保存并启用'
    if (!duplicated) apiKey.value = ''
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
    <div class="setup-card">
      <div class="setup-head">
        <h2>API 配置</h2>
        <button class="btn-ghost" @click="emit('back')">返回</button>
      </div>

      <!-- 已有配置 -->
      <section class="panel">
        <div class="panel-title">已有配置</div>
        <div v-if="configs.length" class="cfg-list">
          <div v-for="c in configs" :key="c.id" class="cfg-item" :class="{ active: c.active }">
            <div class="cfg-info">
              <div class="cfg-name">
                {{ c.name }}
                <span v-if="c.active" class="using-tag">使用中</span>
              </div>
              <div class="cfg-meta">{{ c.model }} · {{ c.masked_key }}<template v-if="c.base_url"> · {{ c.base_url.replace('https://', '').split('/')[0] }}</template></div>
            </div>
            <div class="cfg-actions">
              <button v-if="!c.active" class="btn-sm" :disabled="loading" @click="onActivate(c)">切换</button>
              <button class="btn-sm danger" :disabled="loading" @click="onDelete(c)">删除</button>
            </div>
          </div>
        </div>
        <div v-else class="muted">暂无配置，请在下方添加。</div>
        <div v-if="opError" class="error">{{ opError }}</div>
      </section>

      <!-- 添加配置 -->
      <section class="panel">
        <div class="panel-title">添加配置</div>
        <p class="muted sub">OpenAI 兼容接口，Key 仅存本机。</p>

        <div class="field">
          <label>配置名称<span class="opt">选填</span></label>
          <input v-model="name" type="text" placeholder="留空则用模型名" />
        </div>
        <div class="field">
          <label>API 地址<span class="req">*</span></label>
          <input v-model="baseUrl" type="text" placeholder="https://api.example.com/v1" />
        </div>
        <div class="field">
          <label>API Key<span class="req">*</span></label>
          <input v-model="apiKey" type="password" placeholder="粘贴 API Key" autocomplete="off" />
        </div>
        <div class="field">
          <label>模型名<span class="req">*</span></label>
          <input v-model="model" type="text" placeholder="视觉模型名" />
        </div>

        <button class="btn primary wide" :disabled="saving" @click="onAdd">
          {{ saving ? '保存中…' : '保存并启用' }}
        </button>
        <div v-if="error" class="error">{{ error }}</div>
        <div v-if="notice" class="notice">{{ notice }}</div>
        <p class="muted sub">支持智谱、通义、豆包、Kimi、OpenRouter 等 OpenAI 兼容视觉接口。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.setup-wrap { display: flex; justify-content: center; }
.setup-card { width: 100%; max-width: 560px; display: flex; flex-direction: column; gap: 14px; }

.setup-head {
  display: flex; justify-content: space-between; align-items: center;
}
.setup-head h2 { font-size: 18px; font-weight: 700; color: var(--text); }
.btn-ghost {
  background: var(--bg-subtle); color: var(--text-muted); padding: 6px 14px;
  font-size: 13px; border: none; border-radius: 8px; cursor: pointer;
}
.btn-ghost:hover { background: var(--bg-hover); color: var(--text); }

/* 统一 panel：无边框，靠底色分组 */
.panel {
  background: var(--bg-subtle);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 10px;
}
.panel-title { font-size: 13px; font-weight: 700; color: var(--text); letter-spacing: 0.5px; }
.sub { font-size: 12px; line-height: 1.6; }

.cfg-list { display: flex; flex-direction: column; gap: 8px; }
.cfg-item {
  display: flex; justify-content: space-between; align-items: center; gap: 10px;
  padding: 10px 12px; background: var(--bg-card); border-radius: 8px;
}
.cfg-item.active { background: var(--primary-soft); }
.cfg-name { font-weight: 600; font-size: 14px; color: var(--text); display: flex; align-items: center; gap: 8px; }
.using-tag {
  padding: 1px 8px; font-size: 11px; font-weight: 600;
  background: var(--primary); color: #fff; border-radius: 999px;
}
.cfg-meta { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.cfg-actions { display: flex; gap: 6px; flex-shrink: 0; }
.btn-sm {
  padding: 5px 12px; font-size: 12px; font-weight: 600; border: none; border-radius: 6px;
  background: var(--primary); color: #fff; cursor: pointer;
}
.btn-sm:hover { background: var(--primary-hover); }
.btn-sm.danger { background: var(--danger); }
.btn-sm.danger:hover { opacity: 0.85; }

.field { display: flex; flex-direction: column; gap: 5px; }
.field label { font-size: 13px; font-weight: 600; color: var(--text); }
.req { color: var(--danger); margin-left: 3px; }
.opt { color: var(--text-faint); font-weight: 400; font-size: 11px; margin-left: 6px; }
.field input {
  padding: 10px 12px; border: none; border-radius: 8px;
  font-size: 14px; width: 100%; box-sizing: border-box;
  background: var(--bg-card); color: var(--text);
}
.field input::placeholder { color: var(--text-faint); }
.field input:focus { outline: 2px solid var(--primary); }

.btn.primary.wide { width: 100%; padding: 11px; font-size: 14px; font-weight: 600; }
.error { color: var(--danger); font-size: 13px; text-align: center; }
.notice {
  color: var(--accent-text); background: var(--accent-soft);
  border-radius: 8px; padding: 8px 12px; font-size: 13px; text-align: center;
}
</style>

import { reactive } from 'vue'

export const api = reactive({
  provider: '',
  model: '',
  mapillary: false,
  modes: {},
  defaultMode: 'local',
  mapTileUrl: '',      // 华为瓦片模板（含 {x}{y}{z}{key}），空则用高德
  mapSource: 'amap',   // huawei | amap
  needsSetup: false,   // 未配置 LLM API Key → 显示设置页
  warmingUp: false,    // 本地模型预热中（禁止上传，显示提示）
  warmupElapsed: 0,    // 预热已耗时（秒）
  localCityEngine: 'clip', // local 模式第二级：clip（本地免费）/ llm（云端猜城市名）
  loaded: false,
})

export async function fetchConfig() {
  try {
    const res = await fetch('/api/config')
    const data = await res.json()
    api.provider = data.provider
    api.model = data.model
    api.mapillary = data.mapillary_enabled
    api.modes = data.modes || {}
    api.defaultMode = data.default_mode || 'local'
    api.mapTileUrl = data.map_tile_url || ''
    api.mapSource = data.map_source || 'amap'
    api.needsSetup = !!data.needs_setup
    api.warmingUp = !!data.warming_up
    api.warmupElapsed = data.warmup_elapsed || 0
    api.localCityEngine = data.local_city_engine === 'llm' ? 'llm' : 'clip'
    api.loaded = true
  } catch {
    api.loaded = false
  }
}

// 保存用户偏好（城市引擎，本机持久化）
export async function savePrefs({ localCityEngine } = {}) {
  const form = new FormData()
  if (localCityEngine === 'clip' || localCityEngine === 'llm') form.append('local_city_engine', localCityEngine)
  try {
    const res = await fetch('/api/prefs', { method: 'POST', body: form })
    const data = await res.json()
    api.localCityEngine = data.local_city_engine === 'llm' ? 'llm' : 'clip'
    return data
  } catch { /* 忽略 */ }
}

// 首次启动：保存用户自己的 LLM API Key（存本机数据目录，不落库）
export async function saveSetup({ apiKey, baseUrl = '', model = '' }) {
  const form = new FormData()
  form.append('api_key', apiKey)
  if (baseUrl) form.append('base_url', baseUrl)
  if (model) form.append('model', model)
  const res = await fetch('/api/setup', { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `保存失败（HTTP ${res.status}）`)
  }
  return res.json()
}

// ---- 多 API 配置管理（保存多个 Key，一键切换，支持增删）----

export async function fetchLLMConfigs() {
  const res = await fetch('/api/llm-configs')
  if (!res.ok) throw new Error(`读取配置失败（HTTP ${res.status}）`)
  const data = await res.json()
  return data.configs || []
}

export async function addLLMConfig({ name = '', apiKey, baseUrl = '', model = '' }) {
  const form = new FormData()
  if (name) form.append('name', name)
  form.append('api_key', apiKey)
  if (baseUrl) form.append('base_url', baseUrl)
  if (model) form.append('model', model)
  const res = await fetch('/api/llm-configs', { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `保存失败（HTTP ${res.status}）`)
  }
  const data = await res.json()
  return { configs: data.configs || [], duplicated: !!data.duplicated }
}

export async function activateLLMConfig(configId) {
  const res = await fetch(`/api/llm-configs/${configId}/activate`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `切换失败（HTTP ${res.status}）`)
  }
  return (await res.json()).configs || []
}

export async function deleteLLMConfig(configId) {
  const res = await fetch(`/api/llm-configs/${configId}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `删除失败（HTTP ${res.status}）`)
  }
  return (await res.json()).configs || []
}

export async function uploadImage(file, mode = 'local', scope = 'world', enableOcr = false, enableBaidu = false, ) {
  // 云端 LLM 定城市且未配置 Key：直接拒绝发送图片（后端 503 双重兜底）
  if (api.needsSetup && api.localCityEngine === 'llm') {
    throw new Error('云端 LLM 定城市需要 API Key：请先到「⚙️ 设置」填写，或切到「本地 CLIP-B/16」城市引擎')
  }
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)
  form.append('scope', scope)
  if (enableOcr) form.append('enable_ocr', '1')
  if (enableBaidu) form.append('enable_baidu', '1')
  const res = await fetch('/api/analyze', { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `上传失败（HTTP ${res.status}）`)
  }
  const data = await res.json()
  return data.task_id
}

export async function fetchTask(taskId) {
  const res = await fetch(`/api/tasks/${taskId}`)
  if (!res.ok) throw new Error(`任务查询失败（HTTP ${res.status}）`)
  const data = await res.json()
  return data.task
}

// 一键重试：后端用保存的原图重新分析（无需重新上传）；mode/scope 留空沿用原任务
export async function retryTask(taskId, mode = '', scope = '') {
  const form = new FormData()
  if (mode) form.append('mode', mode)
  if (scope) form.append('scope', scope)
  const res = await fetch(`/api/tasks/${taskId}/retry`, { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `重试失败（HTTP ${res.status}）`)
  }
  const data = await res.json()
  return data.task_id
}

export function confidenceLabel(level) {
  return {
    exact: '精确（EXIF GPS）',
    street: '街道级',
    city: '城市级',
    country: '国家级',
    none: '⚠ 无证据（示意点）',
    unknown: '未知',
  }[level] || level
}

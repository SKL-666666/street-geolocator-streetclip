<script setup>
import { ref, onMounted, watch } from 'vue'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { api } from '../api'

const props = defineProps({
  candidates: { type: Array, default: () => [] },
  center: { type: Array, default: null }, // [lon, lat]
  focusCandidate: { type: Object, default: null }, // 需要飞到的候选对象（null 不飞）
})

const container = ref(null)
let map = null
let markers = []
let tileErrors = 0
let currentSource = 'esri'  // esri(WGS-84) | tencent(GCJ-02) | huawei(GCJ-02)

// ---------- 地图源调研结论（2026 实测）----------
// Esri World Street Map：全球覆盖、海外内容丰富、CORS 放行、WGS-84（标记零偏移）
// 腾讯：国内快但海外瓦片为低细节底图（GCJ-02）→ 作为 Esri 加载失败时的自动降级
// OSM/OpenFreeMap/Carto：本机网络不可用（0/3 成功），已排除
const ESRI_TILES = ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}']
const TENCENT_TILES = []
for (let i = 0; i < 4; i++) {
  TENCENT_TILES.push(`https://rt${i}.map.gtimg.com/tile?z={z}&x={x}&y={y}&styleid=1&version=192`)
}

function tileUrls() {
  if (api.mapTileUrl) return [api.mapTileUrl]  // 后端配置的备用源（如华为）
  return currentSource === 'tencent' ? TENCENT_TILES : ESRI_TILES
}

// 腾讯瓦片 y 轴 TMS 翻转（MapLibre 不支持 {-y}，手动翻转）
function transformRequest(url, resourceType) {
  if (resourceType === 'Tile' && url.includes('map.gtimg.com')) {
    try {
      const u = new URL(url)
      const z = parseInt(u.searchParams.get('z'), 10)
      const y = parseInt(u.searchParams.get('y'), 10)
      if (!isNaN(z) && !isNaN(y)) {
        u.searchParams.set('y', String((1 << z) - 1 - y))
        return { url: u.toString() }
      }
    } catch { /* 保持原 URL */ }
  }
  return { url }
}

const MIN_STYLE = {
  version: 8,
  sources: {
    base: {
      type: 'raster',
      tiles: tileUrls(),
      tileSize: 256,
      maxzoom: 18,
      attribution: currentSource === 'tencent' ? '© 腾讯地图' : '© Esri',
    },
  },
  layers: [{
    id: 'base',
    type: 'raster',
    source: 'base',
    paint: { 'raster-fade-duration': 0, 'raster-opacity': 1 },
  }],
}

// ---------- WGS-84 → GCJ-02 纠偏（公开算法，高德瓦片坐标系）----------
const A = 6378245.0
const EE = 0.00669342162296594323

function outOfChina(lng, lat) {
  return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271
}

function transformLat(x, y) {
  let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0
  ret += ((20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin((y / 3.0) * Math.PI)) * 2.0) / 3.0
  ret += ((160.0 * Math.sin((y / 12.0) * Math.PI) + 320.0 * Math.sin((y * Math.PI) / 30.0)) * 2.0) / 3.0
  return ret
}

function transformLng(x, y) {
  let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0
  ret += ((20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin((x / 3.0) * Math.PI)) * 2.0) / 3.0
  ret += ((150.0 * Math.sin((x / 12.0) * Math.PI) + 300.0 * Math.sin((x / 30.0) * Math.PI)) * 2.0) / 3.0
  return ret
}

function wgs84ToGcj02(lng, lat) {
  if (outOfChina(lng, lat)) return [lng, lat]
  let dLat = transformLat(lng - 105.0, lat - 35.0)
  let dLng = transformLng(lng - 105.0, lat - 35.0)
  const radLat = (lat / 180.0) * Math.PI
  let magic = Math.sin(radLat)
  magic = 1 - EE * magic * magic
  const sqrtMagic = Math.sqrt(magic)
  dLat = (dLat * 180.0) / (((A * (1 - EE)) / (magic * sqrtMagic)) * Math.PI)
  dLng = (dLng * 180.0) / ((A / sqrtMagic) * Math.cos(radLat) * Math.PI)
  return [lng + dLng, lat + dLat]
}

// 展示坐标：Esri 为 WGS-84（零转换）；腾讯/高德为 GCJ-02（需纠偏）
function display(lon, lat) {
  if (currentSource === 'esri') return [lon, lat]
  return wgs84ToGcj02(lon, lat)
}

function fallbackToTencent() {
  if (currentSource === 'tencent' || !map) return
  currentSource = 'tencent'
  map.getSource('base').setTiles(TENCENT_TILES)
  map.setAttribution('© 腾讯地图')
  renderMarkers()  // 坐标系改变 → 重新放置标记
}

const SRC_LABEL = {
  exif: 'EXIF GPS', llm: 'LLM 假设', prior: '视觉先验', geocode: '地理编码',
  streetview: '街景', kartaview: 'KartaView 街景', country: '国家级示意（几何中心）',
  fallback: '默认示意点（无证据）',
}

function flyToCandidate(cand) {
  if (!map || !cand) return
  const [lon, lat] = display(cand.lon, cand.lat)
  // 缩放级别（收敛版）：国家级示意 5（国家全览），其余 6（城市周边，不再钻到街道级）
  const zoom = cand.source === 'country' ? 5 : 6
  map.flyTo({ center: [lon, lat], zoom, essential: true })
  // 按坐标找到对应 marker 打开弹窗（不依赖下标，杜绝错位）
  const target = markers.find((m) => m && m.getLngLat() &&
    Math.abs(m.getLngLat().lng - lon) < 0.01 && Math.abs(m.getLngLat().lat - lat) < 0.01)
  if (target) target.togglePopup()
}

function flyToCenter() {
  if (!map) return
  const [lon, lat] = props.center || (props.candidates[0] ? display(props.candidates[0].lon, props.candidates[0].lat) : null)
  if (lon == null || lat == null) return
  map.flyTo({ center: [lon, lat], zoom: 6 })
}

function renderMarkers() {
  if (!map) return
  markers.forEach((m) => m.remove())
  markers = []

  // 编号按分数降序（与左侧列表一致）；markers 数组按 candidates 原数组顺序存储，
  // 但定位不依赖下标——flyToCandidate 按坐标匹配 marker（点谁飞谁，杜绝错位）。
  const rankMap = {}
  const order = [...props.candidates]
    .map((c, i) => ({ c, i }))
    .sort((a, b) => b.c.score - a.c.score)
  order.forEach(({ c, i }, rank) => { rankMap[i] = rank + 1 })

  props.candidates.forEach((c, i) => {
    const [lon, lat] = display(c.lon, c.lat)
    const el = document.createElement('div')
    el.className = 'marker'
    el.style.background = rankMap[i] === 1 ? '#dc2626' : '#2563eb'
    el.textContent = rankMap[i]
    const popup = new maplibregl.Popup({ offset: 24, maxWidth: '280px' }).setHTML(`
      <div><b>候选 #${rankMap[i]} · ${c.city || c.city_zh || ''}${c.city_zh && c.city_zh !== c.city ? '（' + c.city_zh + '）' : ''}</b>（得分 ${(c.score * 100).toFixed(0)}）</div>
      <div class="muted">${c.country_zh || c.country || ''}</div>
      <div class="muted">${c.lat.toFixed(5)}, ${c.lon.toFixed(5)}</div>
      <div class="muted">来源：${SRC_LABEL[c.source] || c.source}</div>
      ${c.accuracy_hint ? `<div class="muted" style="color:#b45309">⚠ ${c.accuracy_hint}</div>` : ''}
      ${c.thumbnail_url ? `<img src="${c.thumbnail_url}" width="240" style="border-radius:6px;margin-top:6px"/>` : ''}
      ${(c.evidence || []).map((e) => `<div class="muted">· ${e}</div>`).join('')}
    `)
    const marker = new maplibregl.Marker({ element: el })
      .setLngLat([lon, lat])
      .setPopup(popup)
      .addTo(map)
    markers.push(marker)  // markers[i] = candidates[i] 的标记
  })

  renderCircles()

  const pts = props.candidates.map((c) => display(c.lon, c.lat))
  if (pts.length) {
    const bounds = pts.reduce((b, p) => b.extend(p), new maplibregl.LngLatBounds(pts[0], pts[0]))
    // 自动视野收敛：缩放上限 5（国家/区域级视野，不再自动钻到街道级）
    map.fitBounds(bounds, { padding: 60, maxZoom: 5 })
  } else {
    flyToCenter()
  }
}

function renderCircles() {
  // 国家级示意候选：黄色范围圈（GCJ-02 坐标）
  const features = props.candidates
    .filter((c) => c.source === 'country')
    .map((c) => {
      const [lon, lat] = display(c.lon, c.lat)
      return {
        type: 'Feature',
        properties: { lat },
        geometry: { type: 'Point', coordinates: [lon, lat] },
      }
    })
  if (!map.getSource('country-circles')) {
    map.addSource('country-circles', { type: 'geojson', data: { type: 'FeatureCollection', features } })
    const radiusExpr = [
      '/',
      ['*', 400000, ['^', 2, ['zoom']]],
      ['*', 156543.03392, ['cos', ['*', ['get', 'lat'], 0.0174533]]],
    ]
    map.addLayer({
      id: 'country-circles',
      type: 'circle',
      source: 'country-circles',
      paint: {
        'circle-radius': radiusExpr,
        'circle-color': '#f59e0b',
        'circle-opacity': 0.15,
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#d97706',
        'circle-stroke-opacity': 0.8,
      },
    })
  } else {
    map.getSource('country-circles').setData({ type: 'FeatureCollection', features })
    map.setPaintProperty('country-circles', 'circle-opacity', features.length ? 0.15 : 0)
    map.setPaintProperty('country-circles', 'circle-stroke-opacity', features.length ? 0.8 : 0)
  }
}

onMounted(() => {
  map = new maplibregl.Map({
    container: container.value,
    style: MIN_STYLE,
    center: props.center ? display(props.center[0], props.center[1]) : [116.4, 39.9],
    zoom: 3,
    maxZoom: 18,
    maxParallelImageRequests: 12,
    transformRequest,
  })
  map.addControl(new maplibregl.NavigationControl(), 'top-right')
  map.on('load', renderMarkers)
  // Esri 瓦片加载失败累计 → 自动降级腾讯（快速稳定双保险）
  map.on('error', (e) => {
    if (e?.error?.message?.includes('Tile') || e?.tile) {
      tileErrors++
      if (tileErrors > 8) fallbackToTencent()
    }
  })
})

watch(() => props.candidates, renderMarkers)
watch(() => props.focusCandidate, (cand) => {
  if (cand) flyToCandidate(cand)
})

defineExpose({ flyToCandidate })
</script>

<template>
  <div ref="container" class="map-panel"></div>
</template>

<style scoped>
.map-panel { width: 100%; height: 420px; border-radius: 12px; overflow: hidden; }
/* 矮窗（小窗口/横屏矮布局）→ 地图调矮，保证候选栏可见 */
@media (max-height: 700px) {
  .map-panel { height: 300px; }
}
@media (max-height: 560px) {
  .map-panel { height: 220px; }
}
:deep(.marker) {
  width: 26px; height: 26px;
  border-radius: 50%;
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700;
  border: 2px solid #fff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
  cursor: pointer;
}
</style>

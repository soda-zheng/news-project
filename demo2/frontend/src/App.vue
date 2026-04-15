<template>
  <div class="app-shell" :data-theme="theme">
    <div class="app-nav">
      <div class="app-nav-inner">
        <div class="app-logo" @click="goHome">
          <div class="app-logo-mark">
            <span class="app-logo-tick">✓</span>
          </div>
          <div>财懂了</div>
        </div>
        <div>
          <input type="text" class="app-search" placeholder="搜索股票、板块、财报关键词" />
        </div>
        <div class="app-nav-actions">
          <button class="app-nav-btn" @click="goResearch">智能投研</button>
          <button class="app-nav-btn" @click="goFinancialReport">财报分析</button>
          <button class="app-nav-btn" @click="showFx = true">汇率换算</button>
          <button class="app-nav-btn" @click="showStock = true">行情查询</button>
          <button class="app-nav-btn" @click="toggleTheme">{{ theme === 'dark' ? '浅色' : '深色' }}</button>
        </div>
      </div>
    </div>

    <div class="app-page">
      <HomePage
        v-if="route.name === 'home'"
        :markets="markets"
        :newsErr="newsErr"
        :featuredNews="featuredNews"
        :myNews="myNews"
        :hotTopics="hotTopics"
        :videos="videos"
        :formatSigned="formatSigned"
        :formatTime="formatTime"
        :summarizeVideoTitle="summarizeVideoTitle"
        @open-url="openUrl"
        @pick-topic="onPickTopic"
        @play-video="onPlayVideo"
        @goto-videos="goVideosPage"
        @goto-hot-topics="goHotTopicsPage"
      />
      <VideosPage v-else-if="route.name === 'videos'" :videos="videos" @play-video="onPlayVideo" @go-home="goHome" />
      <HotTopicsRoutePage
        v-else-if="route.name === 'hot-topics'"
        :items="hotTopicsMore"
        :analysis="hotTopicsAnalysis"
        @pick-topic="onPickTopic"
        @go-home="goHome"
      />
      <FinancialReportPage v-else-if="route.name === 'financial-report'" />
      <ResearchPage v-else-if="route.name === 'research'" @go-home="goHome" />
    </div>

    <footer class="app-disclaimer" aria-label="免责声明">
      <div class="app-disclaimer-inner">
        <p>风险提示：本产品提供的行情、资讯、视频及由算法/模型生成的分析内容，仅供学习与研究参考，均不构成投资建议。</p>
        <p>市场有风险，投资需谨慎。请结合自身风险承受能力独立判断，因使用相关信息造成的任何损失需自行承担。</p>
        <p>第三方数据与视频版权归原提供方所有，展示数据可能存在延迟、缺失或口径差异，请以权威渠道披露为准。</p>
      </div>
    </footer>

    <FxModal v-model:open="showFx" />
    <StockModal v-model:open="showStock" :initialSymbol="pickedSymbol" />
    <VideoModal v-model:open="showVideo" :video="pickedVideo" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FxModal from './FxModal.vue'
import StockModal from './StockModal.vue'
import VideoModal from './VideoModal.vue'
import HomePage from './pages/HomePage.vue'
import VideosPage from './pages/VideosPage.vue'
import HotTopicsRoutePage from './pages/HotTopicsRoutePage.vue'
import ResearchPage from './pages/ResearchPage.vue'
import FinancialReportPage from './pages/FinancialReportPageImpl.vue'
import { useQuotes } from './composables/useQuotes'
import { useHotTopics } from './composables/useHotTopics'
import { useVideos } from './composables/useVideos'
import { useNews } from './composables/useNews'

const router = useRouter()
const route = useRoute()
const showFx = ref(false)
const showStock = ref(false)
const pickedSymbol = ref('')
const showVideo = ref(false)
const pickedVideo = ref(null)
const theme = ref(localStorage.getItem('theme') || 'light')

const { markets, start: startQuotes, stop: stopQuotes } = useQuotes()
const { hotTopics, hotTopicsMore, hotTopicsAnalysis, loadMore, start: startTopics, stop: stopTopics } = useHotTopics()
const { videos, summarizeVideoTitle, start: startVideos, stop: stopVideos } = useVideos()
// 新闻：开启自动拉取，便于你测试“智能投研/分析功能”联动展示
const { featuredNews, myNews, newsErr, start: startNews, stop: stopNews } = useNews({ paused: false })

function formatSigned(v) {
  const n = Number(v ?? 0)
  if (Number.isNaN(n)) return '0'
  return n > 0 ? `+${n}` : `${n}`
}
function formatTime(ts) {
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function openUrl(url) {
  const u = String(url || '').trim()
  if (!u) return
  window.open(u, '_blank')
}
function goHome() { router.push({ name: 'home' }) }
function goVideosPage() { router.push({ name: 'videos' }) }
function goResearch() { router.push({ name: 'research' }) }
function goFinancialReport() { router.push({ name: 'financial-report' }) }
async function goHotTopicsPage() {
  await loadMore(50)
  router.push({ name: 'hot-topics' })
}
function onPlayVideo(v) { pickedVideo.value = v; showVideo.value = true }
function onPickTopic(t) { pickedSymbol.value = t?.leader || ''; showStock.value = true }
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  localStorage.setItem('theme', theme.value)
}

// 直接打开 /hot-topics 或刷新时也要拉全量榜单（仅从「更多」进入时才有数据）
watch(
  () => route.name,
  (name) => {
    if (name === 'hot-topics') void loadMore(50)
  },
  { immediate: true },
)

onMounted(() => {
  startQuotes()
  startTopics()
  startNews()
  startVideos()
})
onBeforeUnmount(() => {
  stopQuotes()
  stopTopics()
  stopNews()
  stopVideos()
})
</script>


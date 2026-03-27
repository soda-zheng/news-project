import { ref } from 'vue'
import { getHomeNews } from '../api/client'

/**
 * @param {object} opts
 * @param {boolean} [opts.paused=true] 为 true 时不请求新闻（首页新闻区留空并提示）
 * @param {boolean} [opts.onePerRefresh=false] 为 true 且 paused=false 时，每次刷新只取 1 条要点 + 1 条焦点，减轻接口压力
 */
export function useNews({ paused = true, onePerRefresh = false } = {}) {
  const featuredNews = ref([])
  const myNews = ref([])
  const newsErr = ref('')
  let timer = null

  async function refreshHomeNews() {
    try {
      const n = onePerRefresh ? 1 : 20
      const json = await getHomeNews({ page: 1, num: n })
      if (json.code !== 200) {
        newsErr.value = json.msg || '新闻加载失败'
        return
      }
      newsErr.value = ''
      featuredNews.value = (json.data?.featured || []).slice(0, onePerRefresh ? 1 : 3)
      myNews.value = (json.data?.items || []).slice(0, onePerRefresh ? 1 : 20)
    } catch (e) {
      newsErr.value = String(e?.message || e || '新闻加载失败')
      console.error('刷新首页新闻失败：', e)
    }
  }

  function start() {
    if (paused) {
      newsErr.value = '新闻接口已暂停（调试模式），暂不自动刷新。'
      return
    }
    void refreshHomeNews()
    timer = setInterval(() => void refreshHomeNews(), 60000)
  }
  function stop() { if (timer) clearInterval(timer) }

  return { featuredNews, myNews, newsErr, refreshHomeNews, start, stop }
}


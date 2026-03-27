import { ref } from 'vue'
import { getVideos, resolveVideoCoverUrl } from '../api/client'

export function useVideos() {
  const videos = ref([])
  let timer = null

  async function refreshVideos() {
    try {
      const json = await getVideos()
      if (json.code !== 200) return
      const items = json.data?.items || []
      videos.value = items.map((v) => ({
        ...v,
        cover: resolveVideoCoverUrl(v.cover),
      }))
    } catch (e) {
      console.error('刷新视频失败：', e)
    }
  }

  function summarizeVideoTitle(raw) {
    const t = String(raw || '').trim()
    if (!t) return '未命名视频'
    const cleaned = t.replace(/^[【\[].*?[】\]]\s*/u, '').replace(/\s+/g, ' ').trim()
    const head = cleaned.split(/[：:，,（(]/u)[0]?.trim() || cleaned
    const base = head.length >= 8 ? head : cleaned
    return base.length > 24 ? `${base.slice(0, 24)}...` : base
  }

  function start() {
    void refreshVideos()
    timer = setInterval(() => void refreshVideos(), 5 * 60 * 1000)
  }
  function stop() { if (timer) clearInterval(timer) }

  return { videos, refreshVideos, summarizeVideoTitle, start, stop }
}


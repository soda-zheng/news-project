const { stockShell, hotTags, hotTopicsTop10, featuredNews } = require('../../utils/data')
const { getHotTopics, getHomeNews } = require('../../utils/api')
const { getSelectedCode, setSelectedCode, normalizeCode } = require('../../utils/state')

function pickStock(code) {
  return stockShell(code)
}

Page({
  data: {
    hotTags,
    hotTopicsTop10,
    featuredNews,
    heroStock: pickStock(''),
    loading: false,
    errorText: ''
  },
  onShow() {
    const code = getSelectedCode()
    this.setData({ heroStock: pickStock(code) })
    this.refreshFeed()
  },
  async refreshFeed() {
    this.setData({ loading: true, errorText: '' })
    try {
      const [hotRes, newsRes] = await Promise.all([getHotTopics(10), getHomeNews(1, 6)])
      const hotItems = hotRes && hotRes.data && hotRes.data.items ? hotRes.data.items : []
      const featuredItems = newsRes && newsRes.data && newsRes.data.featured ? newsRes.data.featured : []
      const nextHot = hotRes && hotRes.code === 200 ? hotItems.slice(0, 10) : hotTopicsTop10
      const nextNews = newsRes && newsRes.code === 200 ? featuredItems.slice(0, 3) : featuredNews
      this.setData({
        hotTopicsTop10: nextHot.length ? nextHot : hotTopicsTop10,
        featuredNews: nextNews.length ? nextNews : featuredNews
      })
    } catch (e) {
      this.setData({ errorText: '热点/新闻加载失败' })
    } finally {
      this.setData({ loading: false })
    }
  },
  goAiChat() {
    wx.navigateTo({ url: '/pages/aichat/index' })
  },
  pickTopic(e) {
    const leader = String(e.currentTarget.dataset.leader || '')
    const code = normalizeCode(leader)
    if (!code) {
      wx.showToast({ title: '该条目暂无个股代码', icon: 'none' })
      return
    }
    setSelectedCode(code)
    wx.navigateTo({ url: `/pages/aichat/index?code=${code}` })
  },
  openNews(e) {
    const rawUrl = String(e.currentTarget.dataset.url || '').trim()
    if (!rawUrl) {
      wx.showToast({ title: '该新闻暂无原文链接', icon: 'none' })
      return
    }
    const url = encodeURIComponent(rawUrl)
    wx.navigateTo({ url: `/pages/webview/index?url=${url}` })
  }
})


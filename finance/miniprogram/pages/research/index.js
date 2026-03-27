const { stockData, hotTags, hotTopicsTop10, featuredNews } = require('../../utils/data')
const { formatSigned } = require('../../utils/helpers')
const { getHotTopics, getHomeNews } = require('../../utils/api')
const { getSelectedCode, setSelectedCode, normalizeCode } = require('../../utils/state')

function pickStock(code) {
  const c = String(code || '').trim()
  return stockData[c] || stockData['300750']
}

Page({
  data: {
    hotTags,
    hotTopicsTop10,
    featuredNews,
    heroStock: pickStock('300750'),
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
      const nextHot = hotRes && hotRes.code === 200 ? (hotRes.data?.items || []).slice(0, 10) : hotTopicsTop10
      const nextNews = newsRes && newsRes.code === 200 ? (newsRes.data?.featured || []).slice(0, 3) : featuredNews
      this.setData({
        hotTopicsTop10: nextHot.length ? nextHot : hotTopicsTop10,
        featuredNews: nextNews.length ? nextNews : featuredNews
      })
    } catch (e) {
      this.setData({ errorText: '已回退为本地演示数据' })
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
  formatSigned
})


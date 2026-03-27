Page({
  data: {
    url: ''
  },
  onLoad(query) {
    const u = query && query.url ? decodeURIComponent(String(query.url)) : ''
    if (!u) {
      wx.showToast({ title: '链接无效', icon: 'none' })
      return
    }
    this.setData({ url: u })
  }
})

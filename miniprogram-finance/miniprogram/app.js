App({
  globalData: {
    selectedCode: '300750'
  },
  onLaunch() {
    try {
      const code = wx.getStorageSync('selectedCode')
      if (code) this.globalData.selectedCode = String(code)
    } catch (e) {}
  }
})


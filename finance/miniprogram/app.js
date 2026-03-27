const { getSelectedCode } = require('./utils/state')

App({
  globalData: {
    selectedCode: '300750'
  },
  onLaunch() {
    this.globalData.selectedCode = getSelectedCode()
  }
})


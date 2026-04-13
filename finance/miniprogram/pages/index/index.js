const { getStoredUser, applyWeChatUserProfile } = require('../../utils/auth')

const DEFAULT_AVATAR = '/assets/logo.png'

Page({
  data: {
    userInfo: null,
    showBindModal: false,
    draftAvatar: '',
    draftNickname: '',
  },

  noop() {},

  onShow() {
    const u = getStoredUser()
    this.setData({
      userInfo: u,
      draftNickname: u && u.nickName ? u.nickName : '',
      draftAvatar: u && u.avatarUrl ? u.avatarUrl : '',
    })
  },

  openBindModal() {
    const u = getStoredUser()
    this.setData({
      showBindModal: true,
      draftNickname: u && u.nickName ? u.nickName : this.data.draftNickname,
      draftAvatar: u && u.avatarUrl ? u.avatarUrl : this.data.draftAvatar,
    })
  },

  closeBindModal() {
    this.setData({ showBindModal: false })
  },

  onChooseAvatar(e) {
    const url = e.detail && e.detail.avatarUrl
    if (url) this.setData({ draftAvatar: url })
  },

  onNicknameInput(e) {
    this.setData({ draftNickname: (e.detail && e.detail.value) || '' })
  },

  onConfirmBind() {
    const nick = String(this.data.draftNickname || '').trim()
    if (!nick) {
      wx.showToast({ title: '请先输入昵称', icon: 'none' })
      return
    }
    const avatarUrl = String(this.data.draftAvatar || '').trim() || DEFAULT_AVATAR
    const userInfo = { nickName: nick, avatarUrl }
    applyWeChatUserProfile(userInfo)
    this.setData({ userInfo, showBindModal: false })
    wx.showToast({ title: '绑定成功', icon: 'success' })
  },

  onTryLegacyProfile() {
    wx.getUserProfile({
      desc: '用于展示个人中心并与自选绑定',
      success: (res) => {
        const ui = res && res.userInfo
        if (!ui) {
          wx.showToast({ title: '未返回用户信息', icon: 'none' })
          return
        }
        applyWeChatUserProfile(ui)
        this.setData({
          userInfo: ui,
          draftNickname: ui.nickName || '',
          draftAvatar: ui.avatarUrl || '',
          showBindModal: false,
        })
        wx.showToast({ title: '授权成功', icon: 'success' })
      },
      fail: (err) => {
        const msg = (err && err.errMsg) || '授权失败'
        wx.showModal({
          title: '旧版授权不可用',
          content: `${msg}\n请使用本页「选择头像 + 输入昵称」完成绑定。`,
          showCancel: false,
        })
      },
    })
  },

  onStartTap() {
    const u = getStoredUser()
    if (!u || !u.nickName) {
      this.openBindModal()
      wx.showToast({ title: '请先登录后再使用', icon: 'none' })
      return
    }
    wx.redirectTo({
      url: '/pages/portal/index',
    })
  },
})

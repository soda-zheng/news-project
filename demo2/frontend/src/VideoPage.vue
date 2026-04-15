<template>
  <div class="video-page">
    <header class="vp-hero">
      <button type="button" class="vp-back" @click="$emit('back')" aria-label="返回首页">
        <span class="vp-back-icon" aria-hidden="true">←</span>
        首页
      </button>
      <div class="vp-hero-main">
        <div class="vp-hero-kicker">市场 · 视频解读</div>
        <h1 class="vp-title">视频专区</h1>
        <p class="vp-subtitle">精选宏观、汇率、黄金、原油等财经解读视频</p>
      </div>
    </header>

    <ul class="video-grid">
      <li
        class="video-item clickable"
        v-for="v in videos"
        :key="v.id"
        @click="$emit('play', v)"
      >
        <div class="video-thumbnail">
          <img :src="v.cover" alt="" loading="lazy" />
        </div>
        <div class="video-info">
          <div class="video-title" :title="v.title">{{ summarizeVideoTitle(v.title) }}</div>
          <div class="muted video-meta">
            <span v-if="v.tag">{{ v.tag }}</span>
            <span v-if="v.duration">{{ v.duration }}</span>
            <span v-if="v.type === 'external'">站外</span>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup>
defineProps({
  videos: {
    type: Array,
    default: () => []
  }
})

function summarizeVideoTitle(raw) {
  const t = String(raw || '').trim()
  if (!t) return '未命名视频'
  const cleaned = t
    .replace(/^[【\[].*?[】\]]\s*/u, '')
    .replace(/\s+/g, ' ')
    .trim()
  const head = cleaned.split(/[：:，,（(]/u)[0]?.trim() || cleaned
  const base = head.length >= 8 ? head : cleaned
  return base.length > 30 ? `${base.slice(0, 30)}...` : base
}
</script>


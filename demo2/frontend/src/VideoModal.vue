<template>
  <div
    class="modal-mask"
    :style="{ display: open ? 'flex' : 'none' }"
    @click.self="close"
  >
    <div class="modal modal-video" role="dialog" aria-modal="true" aria-label="视频播放" @click.stop>
      <div class="modal-hd">
        <div class="modal-title">
          <span>🎬</span><span>{{ video?.title || '视频播放' }}</span>
        </div>
        <button class="modal-close" @click="close" aria-label="关闭">✕</button>
      </div>

      <div class="modal-bd">
        <div
          v-if="video?.type === 'embed' && video?.embed_url && showEmbedIframe"
          class="video-player"
        >
          <iframe
            :src="video.embed_url"
            frameborder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; fullscreen; gyroscope; picture-in-picture"
            allowfullscreen
            referrerpolicy="strict-origin-when-cross-origin"
          />
        </div>

        <div
          v-else-if="video?.type === 'embed' && video?.embed_url && !showEmbedIframe"
          class="result modal-zero-margin"
        >
          该视频在站内无法嵌入播放（可能已下架、UP 主限制嵌入或地区策略）。请点击下方「站外打开」到 B 站观看。
        </div>

        <div v-else-if="video?.type === 'mp4' && video?.mp4_url" class="video-player">
          <video :src="video.mp4_url" controls playsinline />
        </div>

        <div v-else class="result modal-zero-margin">
          该视频暂不支持站内播放。
        </div>
      </div>

      <div class="modal-ft">
        <div class="modal-actions modal-actions-between">
          <button class="ghost-btn" @click="close">关闭</button>
          <button
            v-if="video?.open_url"
            class="primary-btn"
            @click="openExternal"
            title="在新窗口打开"
          >
            站外打开
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  video: { type: Object, default: null }
})
const emit = defineEmits(['update:open'])

/** 后端 B 站 view 接口判定下架/异常时为 false；未知仍尝试 iframe */
const showEmbedIframe = computed(() => {
  const v = props.video
  if (!v || v.type !== 'embed' || !v.embed_url) return false
  if (v.embed_ok === false) return false
  return true
})

function close() {
  emit('update:open', false)
}

const openUrl = computed(() => String(props.video?.open_url || '').trim())

function openExternal() {
  if (!openUrl.value) return
  window.open(openUrl.value, '_blank')
}
</script>


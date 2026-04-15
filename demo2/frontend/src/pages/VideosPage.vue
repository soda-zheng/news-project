<template>
  <VideoPage :videos="videos" @play="$emit('play-video', $event)" @back="$emit('go-home')" />
</template>

<script setup>
import VideoPage from '../VideoPage.vue'
defineProps({ videos: Array })
defineEmits(['play-video', 'go-home'])
</script>


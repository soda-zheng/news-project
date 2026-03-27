<template>
  <HotTopicsPage :items="items" :analysis="analysis" @pick="$emit('pick-topic', $event)" @back="$emit('go-home')" />
</template>

<script setup>
import HotTopicsPage from '../HotTopicsPage.vue'
defineProps({ items: Array, analysis: Object })
defineEmits(['pick-topic', 'go-home'])
</script>


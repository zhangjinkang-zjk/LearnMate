<template>
  <section ref="frameRoot" class="video-lesson-frame" aria-label="课程视频讲解">
    <header class="video-lesson-frame__header">
      <div><p class="eyebrow">VIDEO EXPLANATION</p><h2>{{ title || '课程视频讲解' }}</h2></div>
      <button type="button" :title="isFullscreen ? '退出全屏播放' : '全屏播放'" :aria-label="isFullscreen ? '退出全屏播放' : '全屏播放'" @click="toggleFullscreen">
        <Minimize2 v-if="isFullscreen" :size="17" />
        <Maximize2 v-else :size="17" />
      </button>
    </header>
    <iframe :src="src" :title="`${title || '课程'}视频讲解`" allow="autoplay; fullscreen" allowfullscreen></iframe>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Maximize2, Minimize2 } from 'lucide-vue-next'

defineProps({ src: { type: String, required: true }, title: { type: String, default: '' } })

const frameRoot = ref(null)
const isFullscreen = ref(false)

function syncFullscreenState() {
  isFullscreen.value = document.fullscreenElement === frameRoot.value
}

async function toggleFullscreen() {
  if (document.fullscreenElement) {
    await document.exitFullscreen()
    return
  }
  await frameRoot.value?.requestFullscreen()
}

onMounted(() => document.addEventListener('fullscreenchange', syncFullscreenState))
onBeforeUnmount(() => document.removeEventListener('fullscreenchange', syncFullscreenState))
</script>

<style scoped>
.video-lesson-frame { display: grid; min-width: 0; min-height: 0; height: 100%; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; border: 1px solid var(--line); border-radius: 7px; background: #101c17; }
.video-lesson-frame__header { display: flex; align-items: center; justify-content: space-between; gap: 15px; padding: 12px 15px; border-bottom: 1px solid rgba(255, 255, 255, .15); background: #18382d; color: #fff; }.video-lesson-frame__header .eyebrow { margin-bottom: 3px; color: #d8ed9a; font-size: 9px; }.video-lesson-frame__header h2 { margin: 0; font-size: 14px; }.video-lesson-frame__header button { display: grid; width: 32px; height: 32px; place-items: center; border: 1px solid rgba(255, 255, 255, .24); border-radius: 5px; background: transparent; color: #fff; }.video-lesson-frame__header button:hover { background: rgba(255, 255, 255, .1); }.video-lesson-frame iframe { display: block; width: 100%; min-height: 0; height: 100%; border: 0; background: #101c17; }.video-lesson-frame:fullscreen { width: 100vw; height: 100vh; border: 0; border-radius: 0; }
</style>

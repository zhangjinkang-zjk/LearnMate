<template>
  <section ref="frameRoot" class="video-lesson-frame" aria-label="课程视频讲解">
    <button class="video-lesson-frame__fullscreen" type="button" :title="isFullscreen ? '退出全屏播放' : '全屏播放'" :aria-label="isFullscreen ? '退出全屏播放' : '全屏播放'" @click="toggleFullscreen">
      <Minimize2 v-if="isFullscreen" :size="17" />
      <Maximize2 v-else :size="17" />
    </button>
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
.video-lesson-frame { position: relative; min-width: 0; min-height: 0; height: 100%; overflow: hidden; border: 1px solid var(--line); border-radius: 7px; background: #101c17; }
.video-lesson-frame__fullscreen { position: absolute; z-index: 1; top: 12px; right: 12px; display: grid; width: 32px; height: 32px; place-items: center; border: 1px solid rgba(255, 255, 255, .32); border-radius: 5px; background: rgba(16, 28, 23, .7); color: #fff; }.video-lesson-frame__fullscreen:hover { background: rgba(16, 28, 23, .92); }.video-lesson-frame__fullscreen:focus-visible { outline: 2px solid #d8ed9a; outline-offset: 2px; }.video-lesson-frame iframe { display: block; width: 100%; min-height: 0; height: 100%; border: 0; background: #101c17; }.video-lesson-frame:fullscreen { width: 100vw; height: 100vh; border: 0; border-radius: 0; }
</style>

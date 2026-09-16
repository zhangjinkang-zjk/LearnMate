<template>
  <section ref="frameRoot" class="ppt-editor-frame" aria-label="PPT editor">
    <button
      v-if="editorUrl"
      class="ppt-editor-frame__fullscreen"
      type="button"
      :title="isFullscreen ? '退出全屏预览' : '全屏预览'"
      :aria-label="isFullscreen ? '退出全屏预览' : '全屏预览'"
      @click="toggleFullscreen"
    >
      <Minimize2 v-if="isFullscreen" :size="17" />
      <Maximize2 v-else :size="17" />
    </button>
    <iframe
      v-if="editorUrl"
      :key="editorUrl"
      :src="editorUrl"
      :title="`${title || 'PPT'} editor`"
      allow="clipboard-read; clipboard-write; fullscreen"
    ></iframe>
    <div v-else class="ppt-editor-frame__empty">PPT content is not ready for editing.</div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Maximize2, Minimize2 } from 'lucide-vue-next'
import { createPptistEditorUrl, parsePptResourceSlides, toPptistPayload } from '@/utils/pptistAdapter'

const props = defineProps({
  content: { type: [String, Object, Array], default: '' },
  title: { type: String, default: '' },
  themeId: { type: String, default: 'minimal-white' },
})

const editorUrl = ref('')
const frameRoot = ref(null)
const isFullscreen = ref(false)

function loadEditor() {
  const slides = parsePptResourceSlides(props.content)
  editorUrl.value = slides.length
    ? createPptistEditorUrl(toPptistPayload({ title: props.title || 'Zhiban PPT', slides, themeId: props.themeId }))
    : ''
}

watch(() => [props.content, props.title, props.themeId], loadEditor, { immediate: true, deep: true })

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
.ppt-editor-frame { position: relative; min-height: 0; height: 100%; overflow: hidden; border: 1px solid var(--line); border-radius: 7px; background: #fff; }
.ppt-editor-frame iframe { display: block; width: 100%; height: 100%; min-height: 0; border: 0; }
.ppt-editor-frame__fullscreen { position: absolute; top: 10px; right: 10px; z-index: 2; display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid rgba(32, 40, 36, .18); border-radius: 5px; background: rgba(255, 255, 255, .94); color: var(--ink); box-shadow: 0 3px 10px rgba(19, 34, 25, .16); }.ppt-editor-frame__fullscreen:hover { background: #f1f6eb; color: var(--accent-deep); }.ppt-editor-frame__fullscreen:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.ppt-editor-frame__empty { display: grid; min-height: 360px; place-items: center; color: var(--muted); font-size: 13px; }
.ppt-editor-frame:fullscreen { width: 100vw; height: 100vh; border: 0; border-radius: 0; }
@media (max-width: 680px) { .ppt-editor-frame { border-radius: 5px; } }
</style>

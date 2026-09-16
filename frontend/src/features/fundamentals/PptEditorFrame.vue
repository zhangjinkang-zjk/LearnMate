<template>
  <section class="ppt-editor-frame" aria-label="PPT editor">
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
import { ref, watch } from 'vue'
import { createPptistEditorUrl, parsePptResourceSlides, toPptistPayload } from '@/utils/pptistAdapter'

const props = defineProps({
  content: { type: [String, Object, Array], default: '' },
  title: { type: String, default: '' },
  themeId: { type: String, default: 'minimal-white' },
})

const editorUrl = ref('')

function loadEditor() {
  const slides = parsePptResourceSlides(props.content)
  editorUrl.value = slides.length
    ? createPptistEditorUrl(toPptistPayload({ title: props.title || 'Zhiban PPT', slides, themeId: props.themeId }))
    : ''
}

watch(() => [props.content, props.title, props.themeId], loadEditor, { immediate: true, deep: true })
</script>

<style scoped>
.ppt-editor-frame { min-height: min(760px, calc(100vh - 148px)); overflow: hidden; border: 1px solid var(--line); border-radius: 7px; background: #fff; }
.ppt-editor-frame iframe { display: block; width: 100%; height: min(760px, calc(100vh - 148px)); min-height: 620px; border: 0; }
.ppt-editor-frame__empty { display: grid; min-height: 360px; place-items: center; color: var(--muted); font-size: 13px; }
@media (max-width: 680px) { .ppt-editor-frame { min-height: 620px; border-radius: 5px; }.ppt-editor-frame iframe { min-height: 620px; } }
</style>

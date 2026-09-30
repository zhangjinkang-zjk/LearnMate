<template>
  <section class="learning-video-panel" aria-label="学习视频">
    <header class="learning-video-panel__header">
      <div>
        <p class="eyebrow">LEARNING VIDEOS</p>
        <h2>学习视频</h2>
        <p>为当前章节找到的相关学习内容。</p>
      </div>
      <span v-if="videos.length" class="learning-video-panel__count">{{ videos.length }} 个结果</span>
    </header>

    <div v-if="isLoading" class="learning-video-panel__state" aria-live="polite">
      <LoaderCircle class="spin" :size="24" />
      <strong>正在查找学习视频</strong>
      <p>结果准备好后会显示在这里。</p>
    </div>

    <div v-else-if="error" class="learning-video-panel__state learning-video-panel__state--error" role="status">
      <CircleAlert :size="24" />
      <strong>学习视频暂时不可用</strong>
      <p>{{ error }}</p>
      <button class="button button--quiet" type="button" @click="$emit('retry')"><RotateCw :size="14" />重新查找</button>
    </div>

    <div v-else-if="!videos.length" class="learning-video-panel__state">
      <PlayCircle :size="24" />
      <strong>暂未找到合适的学习视频</strong>
      <p>可以先继续阅读主讲文档，稍后再回来查看。</p>
    </div>

    <template v-else>
      <VideoLessonFrame
        v-if="selectedVideo?.embed_url"
        class="learning-video-panel__player"
        :src="selectedVideo.embed_url"
        :title="selectedVideo.title"
        label="学习视频"
        referrer-policy="no-referrer"
      />
      <a
        v-if="selectedVideo?.embed_url && selectedVideo?.page_url"
        class="learning-video-panel__source-link"
        :href="selectedVideo.page_url"
        target="_blank"
        rel="noreferrer"
      >
        在原页面打开
        <ExternalLink :size="13" />
      </a>

      <section v-else-if="selectedVideo" class="learning-video-panel__fallback">
        <PlayCircle :size="25" />
        <div>
          <strong>{{ selectedVideo.title || '学习视频' }}</strong>
          <p>{{ selectedVideo.description || '该学习视频需要在原页面打开观看。' }}</p>
        </div>
        <a v-if="selectedVideo.page_url" class="button button--primary" :href="selectedVideo.page_url" target="_blank" rel="noreferrer">
          打开视频
          <ExternalLink :size="14" />
        </a>
      </section>

      <div class="learning-video-panel__grid">
        <button
          v-for="video in videos"
          :key="video.id || video.page_url || video.title"
          class="learning-video-card"
          :class="{ 'is-selected': isSelected(video) }"
          type="button"
          @click="$emit('select', video)"
        >
          <span class="learning-video-card__cover">
            <img :src="resourceCoverUrl(video)" :alt="`${video.title || '学习视频'}封面`" @error="handleCoverError($event, video)" />
            <span class="learning-video-card__play"><PlayCircle :size="22" /></span>
            <span v-if="video.duration_text" class="learning-video-card__duration">{{ video.duration_text }}</span>
          </span>
          <span class="learning-video-card__content">
            <span class="learning-video-card__source">{{ video.source_label || '学习视频' }}</span>
            <strong>{{ video.title || '学习视频' }}</strong>
            <small>{{ videoMeta(video) || '相关学习内容' }}</small>
          </span>
        </button>
      </div>
    </template>
  </section>
</template>

<script setup>
import { CircleAlert, ExternalLink, LoaderCircle, PlayCircle, RotateCw } from 'lucide-vue-next'
import VideoLessonFrame from '@/features/fundamentals/VideoLessonFrame.vue'
import { generatedResourceCover, resourceCoverUrl } from '@/utils/resourceCover'

const props = defineProps({
  videos: { type: Array, default: () => [] },
  selectedVideo: { type: Object, default: null },
  isLoading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

defineEmits(['retry', 'select'])

function isSelected(video) {
  return video === props.selectedVideo
    || Boolean(video?.page_url && video.page_url === props.selectedVideo?.page_url)
}

function videoMeta(video) {
  return [video?.author, video?.view_count_text].filter(Boolean).join(' · ')
}

function handleCoverError(event, video) {
  const image = event.currentTarget
  const fallback = generatedResourceCover(video)
  if (!image || image.src === fallback) return
  image.onerror = null
  image.src = fallback
}
</script>

<style scoped>
.learning-video-panel { min-width: 0; min-height: 0; height: 100%; overflow: auto; padding: 4px 2px 18px; }
.learning-video-panel__header { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin: 0 0 14px; padding: 0 4px 12px; border-bottom: 1px solid var(--line); }
.learning-video-panel__header .eyebrow { margin-bottom: 4px; }
.learning-video-panel__header h2 { margin: 0; color: var(--ink); font-size: 18px; }
.learning-video-panel__header p:last-child { margin: 4px 0 0; color: var(--muted); font-size: 11px; }
.learning-video-panel__count { flex: 0 0 auto; color: var(--accent-deep); font-size: 11px; font-weight: 800; }
.learning-video-panel__state { display: grid; min-height: 320px; place-items: center; align-content: center; gap: 9px; padding: 28px; color: var(--accent-deep); text-align: center; }
.learning-video-panel__state strong { color: var(--ink); font-size: 15px; }
.learning-video-panel__state p { max-width: 360px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.65; }
.learning-video-panel__state--error { color: #a66442; }
.learning-video-panel__state .button { display: inline-flex; align-items: center; gap: 6px; margin-top: 5px; }
.learning-video-panel__grid { display: grid; grid-template-columns: repeat(3, minmax(190px, 280px)); justify-content: start; gap: 14px; margin-top: 16px; }
.learning-video-card { min-width: 0; overflow: hidden; padding: 0; border: 1px solid var(--line); border-radius: 8px; background: var(--paper); color: var(--ink); text-align: left; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.learning-video-card:hover, .learning-video-card.is-selected { border-color: #9dbb8d; box-shadow: 0 8px 20px rgba(45, 70, 40, .1); transform: translateY(-1px); }
.learning-video-card:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.learning-video-card__cover { position: relative; display: block; aspect-ratio: 16 / 9; overflow: hidden; background: #183d34; }
.learning-video-card__cover img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform .25s ease; }
.learning-video-card:hover img, .learning-video-card.is-selected img { transform: scale(1.04); }
.learning-video-card__play { position: absolute; inset: 0; display: grid; place-items: center; background: rgba(15, 31, 25, .28); color: #fff; }
.learning-video-card__duration { position: absolute; right: 7px; bottom: 7px; padding: 3px 5px; border-radius: 3px; background: rgba(11, 25, 19, .82); color: #fff; font-size: 10px; }
.learning-video-card__content { display: grid; min-width: 0; gap: 4px; padding: 8px 10px 10px; }
.learning-video-card__source { overflow: hidden; color: var(--accent-deep); font-size: 10px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.learning-video-card strong { overflow: hidden; font-size: 12px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.learning-video-card small { overflow: hidden; color: var(--muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.learning-video-panel__player { height: min(480px, 52vw); min-height: 280px; margin-top: 14px; }
.learning-video-panel__source-link { display: inline-flex; align-items: center; gap: 5px; margin-top: 9px; color: var(--accent-deep); font-size: 11px; font-weight: 800; text-decoration: none; }
.learning-video-panel__source-link:hover { text-decoration: underline; }
.learning-video-panel__source-link:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.learning-video-panel__fallback { display: flex; align-items: center; gap: 12px; margin-top: 14px; padding: 17px; border: 1px solid var(--line); border-radius: 8px; background: #fbfdf9; color: var(--accent-deep); }
.learning-video-panel__fallback > div { min-width: 0; flex: 1; }
.learning-video-panel__fallback strong { display: block; overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.learning-video-panel__fallback p { margin: 4px 0 0; color: var(--muted); font-size: 11px; line-height: 1.55; }
.learning-video-panel__fallback .button { flex: 0 0 auto; gap: 6px; white-space: nowrap; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) { .learning-video-panel__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.learning-video-panel__player { height: 56vw; min-height: 220px; }.learning-video-panel__fallback { align-items: flex-start; flex-wrap: wrap; }.learning-video-panel__fallback .button { width: 100%; } }
@media (max-width: 480px) { .learning-video-panel__grid { grid-template-columns: 1fr; }.learning-video-panel__header { align-items: flex-start; flex-direction: column; gap: 7px; }.learning-video-panel__player { height: 58vw; min-height: 180px; } }
</style>

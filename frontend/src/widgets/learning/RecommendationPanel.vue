<template>
  <section class="surface surface-pad recommendation-panel">
    <div class="recommendation-heading"><span class="recommendation-icon">→</span><div><p class="eyebrow">系统推荐</p><h2>{{ title }}</h2></div></div>
    <p class="recommendation-copy">{{ message }}</p>
    <RouterLink v-if="to" class="button button--primary" :to="to">{{ actionLabel }}</RouterLink>
  </section>
</template>

<script setup>
defineProps({ title: { type: String, default: '下一步学习行动' }, message: { type: String, required: true }, to: { type: String, default: '' }, actionLabel: { type: String, default: '开始行动' } })
</script>

<style scoped>
.recommendation-panel { border-color: #ccd9b8; background: #f8fbf2; }
.recommendation-heading { display: flex; align-items: center; gap: 12px; }
.recommendation-icon { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); font-size: 18px; font-weight: 800; }
.recommendation-heading .eyebrow { margin-bottom: 4px; }
.recommendation-heading h2 { margin: 0; font-size: 17px; }
.recommendation-copy { margin: 18px 0; color: var(--muted); font-size: 13px; line-height: 1.7; }
</style>

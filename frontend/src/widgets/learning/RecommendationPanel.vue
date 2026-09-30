<template>
  <section class="surface surface-pad recommendation-panel">
    <div class="recommendation-heading">
      <span class="recommendation-icon" aria-hidden="true">→</span>
      <div>
        <p class="eyebrow">系统推荐</p>
        <h2>{{ title }}</h2>
      </div>
    </div>
    <dl class="recommendation-facts">
      <div v-if="reason" class="recommendation-fact">
        <dt>为什么是它</dt>
        <dd>{{ reason }}</dd>
      </div>
      <div v-if="criteria" class="recommendation-fact">
        <dt>怎么算做完</dt>
        <dd>{{ criteria }}</dd>
      </div>
    </dl>
    <RouterLink v-if="to" class="button button--primary recommendation-action" :to="to">{{ actionLabel }}</RouterLink>
  </section>
</template>

<script setup>
// 「现在做什么」这张卡片，数据全部来自 /study/overview 的 recommendation。
//
// 后端的 reason（为什么是它）和 criteria（怎么算做完）一直在算，只是以前的页面没渲染，
// 只拿来给摘要文案兜底 —— 于是"系统推荐你学这个"就成了一句没有依据的话。这里把它们摆出来。
//
// criteria 可以是 null（没有当前节点时后端给的就是 null），那种情况下整行不出现，
// 而不是画一行空的「怎么算做完：」。
defineProps({
  title: { type: String, required: true },
  reason: { type: String, default: '' },
  criteria: { type: String, default: '' },
  // 对象形式（{ name, query }）也要能吃：目的地把当前节点带过去，基础学习页按
  // route.query.pathId / .node 落位。
  to: { type: [String, Object], default: '' },
  actionLabel: { type: String, default: '开始行动' },
})
</script>

<style scoped>
.recommendation-panel { border-color: #ccd9b8; background: #f8fbf2; }
.recommendation-heading { display: flex; align-items: center; gap: 12px; }
.recommendation-icon { display: grid; width: 30px; height: 30px; flex: 0 0 30px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); font-size: 18px; font-weight: 800; }
.recommendation-heading .eyebrow { margin-bottom: 4px; }
.recommendation-heading h2 { margin: 0; font-size: 19px; line-height: 1.45; }
/* auto-fit：只有「为什么是它」时占满一行，两条都在时宽屏并排、窄屏自动落成上下两行。 */
.recommendation-facts { display: grid; gap: 14px 28px; margin: 18px 0 20px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.recommendation-fact { display: grid; grid-template-columns: 76px minmax(0, 1fr); align-items: baseline; gap: 12px; }
.recommendation-fact dt { color: var(--muted); font-size: 11px; line-height: 1.6; }
.recommendation-fact dd { margin: 0; color: var(--ink); font-size: 13px; line-height: 1.7; }
.recommendation-action { display: inline-flex; align-items: center; gap: 6px; text-decoration: none; }
@media (max-width: 620px) {
  .recommendation-fact { grid-template-columns: minmax(0, 1fr); gap: 3px; }
}
</style>

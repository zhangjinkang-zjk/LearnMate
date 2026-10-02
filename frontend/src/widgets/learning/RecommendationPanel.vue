<template>
  <section class="surface surface-pad recommendation-panel">
    <div class="recommendation-heading">
      <span class="recommendation-icon" aria-hidden="true">→</span>
      <div>
        <p class="eyebrow">{{ stepLabel }}</p>
        <h2>{{ title }}</h2>
      </div>
    </div>

    <!-- 「点下去要花什么代价」——知识点数、资料数、任务进度。全部来自节点的既有数据，
         没有一个是估出来的。（这里刻意**不写预计时长**：系统里没有任何时长预估的来源。） -->
    <ul v-if="meta.length" class="recommendation-meta">
      <li v-for="item in meta" :key="item">{{ item }}</li>
    </ul>

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
// 只拿来给摘要文案兜底 —— 于是"系统推荐你学这个"就成了一句没有依据的话。这里把它们摆出来，
// 因为**推荐理由是"个性化系统"和"随便推一个"的分水岭**。
//
// reason / criteria 都可以为空（没有当前节点时后端给的是 null），那种情况下整行不出现，
// 而不是画一行空的「怎么算做完：」。
defineProps({
  title: { type: String, required: true },
  // 元信息，形如 ["3 个知识点", "4 份资料", "已完成 2/5 个任务"]。空数组时整行不出现。
  meta: { type: Array, default: () => [] },
  reason: { type: String, default: '' },
  criteria: { type: String, default: '' },
  // 对象形式（{ name, query }）也要能吃：目的地把当前节点带过去，基础学习页按
  // route.query.pathId / .node 落位。
  to: { type: [String, Object], default: '' },
  actionLabel: { type: String, default: '开始行动' },
  // 「继续学习」/「下一步」—— 由页面决定，组件里不猜。
  stepLabel: { type: String, default: '系统推荐' },
})
</script>

<style scoped>
/* 全页只有这一个主按钮，所以这张卡的视觉权重必须明确高于下面两条信息带。 */
.recommendation-panel { border-color: #ccd9b8; background: #f8fbf2; }
.recommendation-heading { display: flex; align-items: center; gap: 12px; }
.recommendation-icon { display: grid; width: 30px; height: 30px; flex: 0 0 30px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); font-size: 18px; font-weight: 800; }
.recommendation-heading .eyebrow { margin: 0 0 4px; color: var(--accent-deep); }
.recommendation-heading h2 { margin: 0; color: var(--ink); font-size: 22px; line-height: 1.35; }

.recommendation-meta { display: flex; flex-wrap: wrap; gap: 6px 8px; margin: 12px 0 0; padding: 0; list-style: none; }
.recommendation-meta li { padding: 3px 9px; border-radius: 99px; background: #eaf1dc; color: var(--accent-deep); font-size: 11px; font-weight: 800; }

/* auto-fit：只有「为什么是它」时占满一行，两条都在时宽屏并排、窄屏自动落成上下两行。 */
.recommendation-facts { display: grid; gap: 14px 28px; margin: 16px 0 18px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.recommendation-fact { display: grid; grid-template-columns: 76px minmax(0, 1fr); align-items: baseline; gap: 12px; }
.recommendation-fact dt { color: var(--muted); font-size: 11px; line-height: 1.6; }
.recommendation-fact dd { margin: 0; color: var(--ink); font-size: 13px; line-height: 1.7; }
.recommendation-action { display: inline-flex; align-items: center; gap: 6px; min-height: 44px; padding: 0 22px; font-size: 13px; text-decoration: none; }
@media (max-width: 620px) {
  .recommendation-fact { grid-template-columns: minmax(0, 1fr); gap: 3px; }
}
</style>

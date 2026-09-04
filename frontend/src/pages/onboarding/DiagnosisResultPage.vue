<template>
  <main class="result-page">
    <ImmersiveOnboardingBackdrop />
    <RouterLink class="back-link" to="/onboarding/diagnosis"><span aria-hidden="true">←</span><span>BACK</span></RouterLink>
    <header class="result-heading"><p class="eyebrow">诊断结果确认</p><h1>你的学习起点已经生成</h1><p>结果会作为后续任务分析和课程难度的基线，你也可以返回重新诊断。</p></header>
    <div class="result-grid">
      <section class="result-card score-card">
        <span class="score-label">当前综合起点</span>
        <strong>{{ level }}</strong>
        <div class="score-ring"><span>{{ score }}<small>%</small></span></div>
        <p>{{ description }}</p>
      </section>
      <section class="result-card result-list">
        <h2>建议学习顺序</h2>
        <ol>
          <li><span>01</span><div><strong>基础讲解</strong><small>补齐当前方向的关键概念和方法</small></div></li>
          <li><span>02</span><div><strong>迁移练习</strong><small>在小任务中验证是否能独立应用</small></div></li>
          <li><span>03</span><div><strong>进阶案例</strong><small>结合你的目标完成可验证的综合任务</small></div></li>
        </ol>
        <div class="result-actions"><RouterLink class="button button--quiet" to="/onboarding/diagnosis">重新诊断</RouterLink><RouterLink class="button button--primary" to="/learning/overview">进入学习概览</RouterLink></div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed } from 'vue'
import ImmersiveOnboardingBackdrop from '@/shared/ui/ImmersiveOnboardingBackdrop.vue'

let storedResult = {}
try { storedResult = JSON.parse(localStorage.getItem('learnmate_diagnosis_result') || '{}') } catch { storedResult = {} }
const score = computed(() => Math.round(Number(storedResult.percentage ?? 42)))
const level = computed(() => score.value >= 85 ? '应用进阶期' : score.value >= 60 ? '基础巩固期' : '基础建立期')
const description = computed(() => storedResult.message || '你已经理解部分概念，下一步适合通过基础讲解建立完整方法，再进入项目练习。')
</script>

<style scoped>
@font-face { font-family: "Smiley Sans"; src: url("../../shared/assets/fonts/SmileySans-Oblique.woff2") format("woff2"); font-style: normal; font-display: swap; }
.result-page { position: relative; min-height: 100vh; overflow: hidden; isolation: isolate; padding: clamp(28px, 5vw, 64px) clamp(20px, 6vw, 90px) 56px; color: #f3f0e7; background: #1e3c34; }.back-link { position: relative; z-index: 2; display: inline-flex; align-items: center; gap: 10px; color: rgba(243, 240, 231, .8); font-size: 11px; font-weight: 800; letter-spacing: .16em; text-decoration: none; }.back-link:hover { color: #e2f452; }.back-link span:first-child { font-size: 20px; line-height: .6; }.result-heading { position: relative; z-index: 1; width: min(980px, 100%); margin: clamp(38px, 8vh, 86px) auto 30px; }.result-heading .eyebrow { color: #d9ed9a; }.result-heading h1 { margin: 0; color: #f3f0e7; font-family: "Smiley Sans", Georgia, serif; font-size: clamp(30px, 4.5vw, 52px); font-weight: 500; letter-spacing: .01em; line-height: 1.15; }.result-heading > p:last-child { max-width: 600px; margin: 14px 0 0; color: rgba(243, 240, 231, .72); font-size: 14px; line-height: 1.8; }.result-grid { position: relative; z-index: 1; display: grid; grid-template-columns: minmax(0, .85fr) minmax(0, 1.15fr); gap: 18px; width: min(980px, 100%); margin: 0 auto; }.result-card { border: 1px solid rgba(243, 240, 231, .22); border-radius: 8px; background: rgba(9, 29, 21, .72); box-shadow: 0 20px 55px rgba(2, 15, 10, .22); }.score-card { display: grid; gap: 12px; align-content: start; padding: 28px; }.score-label { color: rgba(243, 240, 231, .68); font-size: 12px; }.score-card strong { color: #f3f0e7; font-size: 22px; }.score-ring { display: grid; width: 132px; height: 132px; margin: 15px 0 8px; place-items: center; border: 13px solid rgba(220, 232, 177, .3); border-right-color: #e2f452; border-bottom-color: #e2f452; border-radius: 50%; }.score-ring span { font-size: 30px; font-weight: 800; }.score-ring small { font-size: 14px; }.score-card p { margin: 0; color: rgba(243, 240, 231, .72); font-size: 13px; line-height: 1.7; }.result-list { padding: 28px; }.result-list h2 { margin: 0 0 18px; color: #f3f0e7; font-size: 18px; }.result-list ol { display: grid; gap: 18px; margin: 0; padding: 0; list-style: none; }.result-list li { display: flex; gap: 13px; }.result-list li > span { color: #e2f452; font-size: 12px; font-weight: 800; }.result-list li div { display: grid; gap: 4px; }.result-list li strong { color: #f3f0e7; }.result-list small { color: rgba(243, 240, 231, .65); font-size: 12px; }.result-actions { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 25px; }.result-actions .button--primary { background: #e2f452; color: #1e3c34; }.result-actions .button--quiet { border-color: rgba(243, 240, 231, .3); background: transparent; color: #f3f0e7; }
@media (max-width: 760px) { .result-grid { grid-template-columns: 1fr; } }
</style>

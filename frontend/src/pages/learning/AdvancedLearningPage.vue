<template>
  <div>
    <PageTitle
      eyebrow="进阶学习"
      title="把知识用到真实目标中"
      description="围绕你的学习目标完成一次可验证的任务；系统只给出情境、材料和标准，关键判断由你完成。"
    >
      <template #actions>
        <button class="button button--quiet" type="button" :disabled="loading" @click="loadTask">
          <RefreshCw :size="15" />
          重新同步
        </button>
      </template>
    </PageTitle>

    <section v-if="loading" class="surface surface-pad state-panel" aria-live="polite">
      <LoaderCircle class="spin" :size="20" />
      <div><strong>正在生成当前进阶任务</strong><p>系统正在读取你的学习目标、路径进度和能力诊断。</p></div>
    </section>

    <section v-else-if="errorMessage" class="surface surface-pad state-panel state-panel--error">
      <CircleAlert :size="20" />
      <div><strong>暂时无法读取进阶任务</strong><p>{{ errorMessage }}</p></div>
      <button class="button button--quiet" type="button" @click="loadTask">重试</button>
    </section>

    <section v-else-if="!task" class="surface surface-pad empty-panel">
      <p class="eyebrow">进阶学习</p>
      <h2>正在生成当前进阶任务</h2>
      <p>系统正在根据你的学习目标、路径进度和能力诊断生成任务内容。</p>
    </section>

    <template v-else>
      <section class="task-banner">
        <div class="task-banner__copy">
          <div class="task-tags">
            <span>{{ profile.direction || '正在生成' }}</span>
            <span>{{ goalModeLabel }}</span>
            <span>路径 {{ path.stage || '正在生成' }}</span>
          </div>
          <p class="eyebrow">当前任务</p>
          <h2>{{ task.title }}</h2>
          <p>{{ task.brief }}</p>
        </div>
        <div class="task-progress" aria-label="学习路径完成度">
          <strong>{{ path.progress }}%</strong>
          <span>路径进度</span>
          <div class="progress-track"><div class="progress-value" :style="{ width: `${path.progress}%` }"></div></div>
        </div>
      </section>

      <div class="task-layout">
        <main class="task-main">
          <section class="surface surface-pad task-brief">
            <div class="section-heading">
              <div><p class="eyebrow">任务情境</p><h3>现在要解决什么</h3></div>
              <span class="focus-chip">重点能力：{{ task.focus }}</span>
            </div>
            <p class="problem-copy">{{ task.problem }}</p>
            <ul class="constraint-list">
              <li v-for="constraint in task.constraints" :key="constraint"><span></span>{{ constraint }}</li>
            </ul>
            <div class="task-action-row">
              <RouterLink class="button button--primary" :to="workspaceLink">进入任务工作区 <ArrowRight :size="15" /></RouterLink>
              <span>{{ task.resources.length ? `已关联 ${task.resources.length} 份当前节点材料` : '进入后可生成或补充任务材料' }}</span>
            </div>
          </section>

          <section class="surface surface-pad recommendation">
            <div class="recommendation-icon"><Route :size="18" /></div>
            <div><p class="eyebrow">为什么是这个任务</p><p>{{ task.recommendation }}</p></div>
          </section>
        </main>

        <aside class="surface task-standard">
          <section class="standard-section">
            <p class="eyebrow">本次交付</p>
            <h3>完成后需要留下什么</h3>
            <ul class="deliverable-list">
              <li v-for="item in task.deliverables" :key="item.id"><span class="check-box"></span><span>{{ item.label }}</span></li>
            </ul>
          </section>
          <section class="standard-section">
            <p class="eyebrow">验收标准</p>
            <ol class="criteria-list">
              <li v-for="(criterion, index) in task.criteria" :key="criterion"><span>{{ index + 1 }}</span><p>{{ criterion }}</p></li>
            </ol>
          </section>
        </aside>
      </div>

      <section class="surface stage-panel">
        <div class="stage-heading"><div><p class="eyebrow">任务阶段</p><h3>从理解到可验证成果</h3></div><span>当前：{{ activeStage?.label || '正在生成' }}</span></div>
        <ol class="stage-list">
          <li v-for="(stage, index) in task.stages" :key="stage.id" :class="`is-${stage.status}`">
            <div class="stage-index"><Check v-if="stage.status === 'completed'" :size="15" /><span v-else>{{ String(index + 1).padStart(2, '0') }}</span></div>
            <div><strong>{{ stage.label }}</strong><small>{{ stageDescription[stage.id] }}</small></div>
          </li>
        </ol>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ArrowRight, Check, CircleAlert, LoaderCircle, RefreshCw, Route } from 'lucide-vue-next'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { advancedLearningApi } from '@/shared/api/advancedLearningApi'

const loading = ref(true)
const errorMessage = ref('')
const task = ref(null)
const profile = reactive({ identity: '', direction: '', goal: '' })
const path = reactive({ id: null, stage: '', progress: null })

const modeLabels = { job: '就业目标', project: '项目目标', transition: '转行目标', foundation: '系统学习', competition: '竞赛目标', exam: '考试目标', custom: '自定义目标' }
const stageDescription = { context: '理解任务背景与限制', plan: '形成方案并说明取舍', verify: '用数据或材料验证', review: '复盘结论并完成答辩' }
const goalModeLabel = computed(() => modeLabels[task.value?.mode] || '正在生成')
const activeStage = computed(() => task.value?.stages.find((stage) => stage.status === 'active'))
const workspaceLink = computed(() => ({ path: '/learning/workspace', query: { mode: 'advanced', taskId: task.value?.id, pathId: task.value?.workspace.path_id, nodeId: task.value?.workspace.node_id } }))
const unwrap = (response) => response?.data?.data ?? response?.data ?? null

async function loadTask() {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = unwrap(await advancedLearningApi.getCurrentTask())
    Object.assign(profile, result?.profile || {})
    Object.assign(path, result?.path || { id: null, stage: '', progress: null })
    task.value = result?.status === 'ready' ? result.task : null
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || '请检查后端服务后重新同步。'
  } finally {
    loading.value = false
  }
}

onMounted(loadTask)
</script>

<style scoped>
.button { gap: 8px; }
.button:disabled { cursor: wait; opacity: .55; }
.state-panel { display: flex; align-items: center; gap: 14px; min-height: 96px; color: var(--accent-deep); }
.state-panel div { flex: 1; }
.state-panel p, .empty-panel p { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.7; }
.state-panel--error { color: #954e38; }
.spin { animation: spin 1s linear infinite; }
.empty-panel { max-width: 720px; }
.empty-panel h2 { margin: 0; font-size: 22px; }
.empty-panel > p:not(.eyebrow) { margin-bottom: 20px; }
.task-banner { display: grid; grid-template-columns: minmax(0, 1fr) 160px; gap: 30px; align-items: end; margin-bottom: 18px; padding: 4px 4px 24px; border-bottom: 1px solid var(--line); }
.task-tags { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 22px; }
.task-tags span, .focus-chip { padding: 5px 8px; border: 1px solid #dbe5d5; border-radius: 4px; background: #f8fbf4; color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.task-banner h2 { max-width: 760px; margin: 0; font-size: 26px; line-height: 1.35; }
.task-banner__copy > p:last-child { max-width: 700px; margin: 10px 0 0; color: var(--muted); font-size: 13px; line-height: 1.75; }
.task-progress { display: grid; gap: 5px; text-align: right; }
.task-progress strong { color: var(--accent-deep); font-size: 28px; }
.task-progress span { color: var(--muted); font-size: 10px; }
.task-progress .progress-track { margin-top: 5px; }
.task-layout { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(300px, .75fr); gap: 18px; align-items: stretch; }
.task-main { display: grid; gap: 18px; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.section-heading h3, .task-standard h3, .stage-heading h3 { margin: 0; font-size: 18px; }
.problem-copy { margin: 20px 0; color: var(--ink); font-size: 15px; line-height: 1.8; }
.constraint-list, .deliverable-list, .criteria-list, .stage-list { margin: 0; padding: 0; list-style: none; }
.constraint-list { display: grid; gap: 11px; padding: 16px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.constraint-list li { display: flex; align-items: flex-start; gap: 10px; color: var(--muted); font-size: 12px; line-height: 1.6; }
.constraint-list li > span { flex: 0 0 auto; width: 5px; height: 5px; margin-top: 7px; border-radius: 50%; background: var(--accent-deep); }
.task-action-row { display: flex; align-items: center; gap: 14px; margin-top: 20px; }
.task-action-row > span { color: var(--muted); font-size: 10px; }
.recommendation { display: flex; gap: 14px; border-color: #d7e3c9; background: #f8fbf2; }
.recommendation-icon { display: grid; flex: 0 0 auto; width: 34px; height: 34px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); }
.recommendation p:last-child { margin: 0; color: #445047; font-size: 12px; line-height: 1.75; }
.task-standard { overflow: hidden; }
.standard-section { padding: 22px; }
.standard-section + .standard-section { border-top: 1px solid var(--line); }
.deliverable-list { display: grid; gap: 14px; margin-top: 20px; }
.deliverable-list li { display: flex; align-items: center; gap: 10px; color: var(--ink); font-size: 12px; }
.check-box { width: 15px; height: 15px; border: 1px solid #b9c5bb; border-radius: 3px; }
.criteria-list { display: grid; gap: 13px; margin-top: 17px; }
.criteria-list li { display: grid; grid-template-columns: 22px 1fr; gap: 9px; align-items: start; }
.criteria-list span { display: grid; width: 22px; height: 22px; place-items: center; border-radius: 50%; background: var(--soft); color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.criteria-list p { margin: 2px 0 0; color: var(--muted); font-size: 11px; line-height: 1.55; }
.stage-panel { margin-top: 18px; padding: 22px; }
.stage-heading { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }
.stage-heading > span { color: var(--accent-deep); font-size: 11px; font-weight: 800; }
.stage-list { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 22px; border-top: 1px solid var(--line); }
.stage-list li { position: relative; display: flex; gap: 11px; min-width: 0; padding: 20px 12px 0 0; }
.stage-list li:not(:last-child)::after { position: absolute; top: -2px; right: 14px; left: 35px; height: 3px; background: var(--line); content: ''; }
.stage-list li.is-active::after { background: linear-gradient(90deg, var(--accent-deep) 35%, var(--line) 35%); }
.stage-index { position: relative; z-index: 1; display: grid; flex: 0 0 auto; width: 27px; height: 27px; place-items: center; margin-top: -35px; border: 1px solid var(--line); border-radius: 50%; background: var(--paper); color: var(--muted); font-size: 9px; font-weight: 800; }
.is-active .stage-index { border-color: var(--accent-deep); background: var(--accent-deep); color: #fff; }
.is-completed .stage-index { border-color: var(--accent); background: var(--accent); color: var(--accent-deep); }
.stage-list strong, .stage-list small { display: block; }
.stage-list strong { font-size: 12px; }
.stage-list small { margin-top: 5px; color: var(--muted); font-size: 10px; line-height: 1.45; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .task-layout { grid-template-columns: 1fr; }.stage-list { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px 0; }.stage-list li:nth-child(2)::after { display: none; } }
@media (max-width: 600px) { .task-banner { grid-template-columns: 1fr; }.task-progress { text-align: left; }.section-heading, .stage-heading, .task-action-row { align-items: flex-start; flex-direction: column; }.focus-chip { white-space: normal; }.stage-list { grid-template-columns: 1fr; border-top: 0; }.stage-list li { padding: 0 0 0 39px; }.stage-list li:not(:last-child)::after { top: 28px; bottom: -22px; left: 13px; width: 2px; height: auto; }.stage-index { position: absolute; top: 0; left: 0; margin: 0; } }
</style>

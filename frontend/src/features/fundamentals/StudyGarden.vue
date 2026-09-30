<template>
  <section class="forest-review surface" aria-labelledby="forest-review-title">
    <header class="forest-review__header">
      <div>
        <p class="eyebrow">LEARNING FOREST</p>
        <h2 id="forest-review-title">学习树林</h2>
      </div>
      <div class="forest-review__count" aria-label="已完成章节数量">
        <strong>{{ completedNodes.length }}</strong><span>/ {{ nodes.length }}</span>
      </div>
    </header>

    <div v-if="activeNode" class="forest-focus">
      <div class="forest-focus__copy">
        <span class="forest-focus__eyebrow">CURRENT TREE</span>
        <h3>{{ activeNode.title }}</h3>
        <p>{{ stageTitle }}</p>
        <dl class="forest-focus__milestones">
          <div :class="{ 'is-done': activeNode.resources_viewed }"><dt>阅读主讲内容</dt><dd>{{ activeNode.resources_viewed ? '已完成' : '待完成' }}</dd></div>
          <div :class="{ 'is-done': activeNode.status === 'completed' }"><dt>完成章节复盘</dt><dd>{{ activeNode.status === 'completed' ? '已完成' : '进行中' }}</dd></div>
        </dl>
      </div>

      <div class="forest-focus__tree-wrap">
        <ForestTree :stage="activeStage" :variant="treeVariant(activeNode, 0)" :label="`${activeNode.title}的成长状态：${stageTitle}`" />
      </div>

      <button class="forest-focus__action" type="button" :disabled="activeNode.status === 'locked'" @click="$emit('select', activeNode.id)">
        <span>第 {{ activeIndex + 1 }} 章</span>
        <strong>{{ activeNode.status === 'completed' ? '再次复盘' : '照料这棵树' }}</strong>
      </button>
    </div>
    <div v-else class="forest-empty">
      <ForestTree :stage="0" label="等待播种的土壤" />
      <p>生成学习路径后，这里会出现第一块可以播种的土地。</p>
    </div>

    <section class="forest-grove" aria-labelledby="forest-grove-title">
      <div class="forest-grove__heading">
        <div><p class="eyebrow">YOUR GROVE</p><h3 id="forest-grove-title">已经长成的树</h3></div>
        <span>{{ completedNodes.length ? `${completedNodes.length} 棵` : '还没有' }}</span>
      </div>
      <div v-if="completedNodes.length" class="forest-grove__trees" role="list">
        <button
          v-for="(node, index) in completedNodes"
          :key="node.id"
          class="grove-tree"
          :class="{ 'is-active': String(node.id) === String(activeNode?.id) }"
          type="button"
          role="listitem"
          :aria-label="`查看已完成章节：${node.title}`"
          @click="$emit('select', node.id)"
        >
          <ForestTree :stage="4" :variant="treeVariant(node, index)" :label="node.title" />
          <span>{{ node.title }}</span>
        </button>
      </div>
      <p v-else class="forest-grove__empty">完成第一章复盘，它会长成树林里的第一棵树。</p>
    </section>

    <section v-if="growingNodes.length" class="forest-seedbed" aria-labelledby="forest-seedbed-title">
      <div class="forest-seedbed__heading"><p class="eyebrow">NEXT TO GROW</p><h3 id="forest-seedbed-title">等待成长</h3></div>
      <div class="forest-seedbed__list">
        <button v-for="node in growingNodes" :key="node.id" type="button" :disabled="node.status === 'locked'" @click="$emit('select', node.id)">
          <i :class="`is-stage-${nodeStage(node)}`" aria-hidden="true"></i><span>{{ node.title }}</span>
        </button>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import ForestTree from '@/features/fundamentals/ForestTree.vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  activeNodeId: { type: [String, Number], default: null },
})

defineEmits(['select'])

const completedNodes = computed(() => props.nodes.filter((node) => node.status === 'completed'))
const growingNodes = computed(() => props.nodes.filter((node) => node.status !== 'completed').slice(0, 6))
const activeNode = computed(() => props.nodes.find((node) => String(node.id) === String(props.activeNodeId)) || props.nodes.find((node) => node.status !== 'locked') || null)
const activeIndex = computed(() => props.nodes.findIndex((node) => String(node.id) === String(activeNode.value?.id)))
const activeStage = computed(() => nodeStage(activeNode.value || {}))
const stageTitle = computed(() => ['等待播种', '种子已经落进土壤', '幼苗正在生长', '树苗等待复盘完成', '这棵树已经长成'][activeStage.value])

function nodeStage(node) {
  if (node.status === 'completed') return 4
  if (node.resources_viewed) return 3
  if (node.status === 'in_progress') return 2
  if (node.status === 'unlocked') return 1
  return 0
}

function treeVariant(node, offset) {
  const id = Number(node?.id) || offset
  return ['round', 'pine', 'willow'][Math.abs(id + offset) % 3]
}
</script>

<style scoped>
.forest-review { padding: 24px; }.forest-review__header { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 17px; }.forest-review h2,.forest-review h3 { margin: 0; color: var(--ink); }.forest-review h2 { font-size: 20px; }.forest-review h3 { font-size: 15px; }.forest-review__count { color: var(--muted); font-size: 13px; }.forest-review__count strong { color: var(--accent-deep); font-size: 28px; line-height: 1; }.forest-review__count span { margin-left: 3px; }
.forest-focus { display: grid; min-height: 285px; grid-template-columns: minmax(190px, .85fr) minmax(230px, 1fr) minmax(145px, .55fr); align-items: center; gap: 18px; padding: 21px 24px 0; overflow: hidden; border: 1px solid #d9e4d5; border-radius: 7px; background: #f4f7f1; }.forest-focus__copy { align-self: start; padding-top: 13px; }.forest-focus__eyebrow { color: #68846a; font-size: 10px; font-weight: 800; letter-spacing: .09em; }.forest-focus__copy h3 { margin-top: 8px; font-size: 18px; line-height: 1.35; }.forest-focus__copy > p { margin: 6px 0 16px; color: var(--muted); font-size: 12px; }.forest-focus__milestones { display: grid; gap: 8px; margin: 0; }.forest-focus__milestones div { display: flex; justify-content: space-between; gap: 10px; padding-top: 8px; border-top: 1px solid #dce7d9; }.forest-focus__milestones dt,.forest-focus__milestones dd { margin: 0; font-size: 10px; }.forest-focus__milestones dt { color: var(--muted); }.forest-focus__milestones dd { color: #a76f48; font-weight: 800; }.forest-focus__milestones .is-done dd { color: #52805c; }
.forest-focus__tree-wrap { position: relative; align-self: end; height: 262px; }.forest-focus__tree-wrap::before { position: absolute; right: 5%; bottom: 0; left: 5%; height: 52px; border-radius: 50% 50% 0 0; background: #dbe9d5; content: ''; }.forest-focus__tree-wrap :deep(.forest-tree) { position: relative; z-index: 1; }
.forest-focus__action { align-self: center; display: grid; gap: 7px; padding: 0; border: 0; background: transparent; color: var(--ink); cursor: pointer; text-align: left; }.forest-focus__action span { color: var(--muted); font-size: 10px; }.forest-focus__action strong { font-size: 13px; }.forest-focus__action:hover:not(:disabled) strong { color: var(--accent-deep); }.forest-focus__action:disabled { cursor: default; opacity: .62; }.forest-focus__action:focus-visible,.grove-tree:focus-visible,.forest-seedbed button:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 3px; }
.forest-grove { margin-top: 20px; }.forest-grove__heading,.forest-seedbed__heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 10px; }.forest-grove__heading span { color: var(--muted); font-size: 11px; }.forest-grove__trees { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; padding: 12px 10px 0; border-bottom: 1px solid #ced9ca; background: #f7faf5; }.grove-tree { display: grid; min-width: 0; grid-template-rows: 106px auto; gap: 2px; padding: 0 5px 10px; border: 0; background: transparent; color: var(--ink); cursor: pointer; }.grove-tree :deep(.forest-tree) { height: 110px; }.grove-tree span { overflow: hidden; color: var(--muted); font-size: 10px; text-align: center; text-overflow: ellipsis; white-space: nowrap; }.grove-tree:hover span,.grove-tree.is-active span { color: var(--accent-deep); font-weight: 800; }.forest-grove__empty { margin: 0; padding: 20px 0; border-bottom: 1px solid #ced9ca; color: var(--muted); font-size: 12px; }
.forest-seedbed { margin-top: 20px; }.forest-seedbed__list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--line); }.forest-seedbed button { display: flex; min-width: 0; align-items: center; gap: 8px; padding: 11px 2px; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: var(--ink); cursor: pointer; text-align: left; }.forest-seedbed button:nth-child(3n + 2) { padding-right: 12px; padding-left: 12px; border-right: 1px solid var(--line); border-left: 1px solid var(--line); }.forest-seedbed button:disabled { cursor: default; opacity: .55; }.forest-seedbed button span { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.forest-seedbed button:hover:not(:disabled) span { color: var(--accent-deep); }.forest-seedbed button i { display: block; width: 12px; height: 12px; flex: 0 0 12px; border-radius: 50%; background: #b9845c; }.forest-seedbed button i.is-stage-2 { background: #8fb17e; }.forest-seedbed button i.is-stage-3 { background: #699b65; }.forest-empty { display: grid; min-height: 245px; grid-template-columns: 170px minmax(0, 1fr); align-items: center; gap: 20px; padding: 0 28px; border: 1px solid #d9e4d5; background: #f4f7f1; }.forest-empty :deep(.forest-tree) { height: 190px; }.forest-empty p { max-width: 260px; color: var(--muted); font-size: 12px; line-height: 1.6; }
@media (max-width: 880px) { .forest-focus { grid-template-columns: 1fr minmax(200px, .8fr); }.forest-focus__action { grid-column: 1 / -1; padding-bottom: 16px; }.forest-grove__trees { grid-template-columns: repeat(4, minmax(0, 1fr)); }.forest-seedbed__list { grid-template-columns: repeat(2, minmax(0, 1fr)); }.forest-seedbed button:nth-child(3n + 2) { padding-right: 2px; padding-left: 2px; border-right: 0; border-left: 0; }.forest-seedbed button:nth-child(2n) { padding-left: 12px; border-left: 1px solid var(--line); } }
@media (max-width: 560px) { .forest-review { padding: 17px; }.forest-focus { grid-template-columns: 1fr; padding: 17px 17px 0; }.forest-focus__copy { padding-top: 0; }.forest-focus__tree-wrap { order: -1; height: 210px; }.forest-focus__action { padding-bottom: 15px; }.forest-grove__trees { grid-template-columns: repeat(3, minmax(0, 1fr)); }.forest-seedbed__list { grid-template-columns: 1fr; }.forest-seedbed button:nth-child(2n) { padding-left: 2px; border-left: 0; }.forest-empty { grid-template-columns: 1fr; gap: 0; padding: 10px 18px 18px; text-align: center; }.forest-empty :deep(.forest-tree) { height: 160px; }.forest-empty p { margin: 0 auto; } }
</style>

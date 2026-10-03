<template>
  <section class="tree-review" :aria-label="`${node.title} 的学习复盘`">
    <span class="tree-review__sun" aria-hidden="true"></span>
    <span class="tree-review__cloud tree-review__cloud--left" aria-hidden="true"></span>
    <span class="tree-review__cloud tree-review__cloud--right" aria-hidden="true"></span>
    <span class="tree-review__hill tree-review__hill--back" aria-hidden="true"></span>
    <span class="tree-review__hill tree-review__hill--front" aria-hidden="true"></span>
    <span class="tree-review__path" aria-hidden="true"></span>
    <span class="tree-review__grass tree-review__grass--one" aria-hidden="true"></span>
    <span class="tree-review__grass tree-review__grass--two" aria-hidden="true"></span>

    <button class="tree-review__back" type="button" @click="$emit('back')"><ArrowLeft :size="15" /> 返回树林</button>

    <header class="tree-review__heading">
      <p class="eyebrow">CHAPTER CHECK</p>
      <h2>{{ node.title }}</h2>
      <p>{{ node.summary || '在这里完成本章复盘，让这棵树继续长大。' }}</p>
    </header>

    <!-- 和花园里是**同一棵**。这里给 `fine` 的叶团粒度：场景里这棵树有 300px 宽，
         花园那棵只有 100px，同一个粒度在两边不可能都合适。 -->
    <div class="tree-review__tree" aria-hidden="true">
      <GrowthTree :node="node" :weak-points="weakPoints" detail="fine" />
    </div>

    <div class="tree-review__data tree-review__data--score">
      <span>最近答题</span>
      <strong>{{ latestScoreLabel }}</strong>
      <small>{{ answerSummary }}</small>
    </div>
    <div class="tree-review__data tree-review__data--mastery">
      <span>掌握度</span>
      <strong>{{ masteryLabel }}</strong>
      <i><b :style="{ width: `${masteryValue}%` }"></b></i>
      <small>{{ masteryEvidence }}</small>
    </div>
    <div class="tree-review__data tree-review__data--weakness">
      <span>错误知识点</span>
      <strong>{{ weakPoints.length || 0 }}</strong>
      <small>{{ weakPointLabel }}</small>
    </div>
    <div class="tree-review__data tree-review__data--next">
      <span>下一步建议</span>
      <strong>{{ nextSuggestionTitle }}</strong>
      <small>{{ nextSuggestionReason }}</small>
    </div>

    <div class="tree-review__actions">
      <!-- 「题目测试」**没有 v-if**：同一张复盘页在不同章节给出不同的按钮，是这一版
           之前最大的那处读不懂 —— 右侧写着「完成本章题目测试」，左边却没有那颗按钮。
           题是现场生成的，任何未锁章节都测得出来。 -->
      <button type="button" @click="$emit('quiz')"><SquareCheck :size="17" /><span>题目测试</span></button>
      <button v-if="canFeynman" type="button" @click="$emit('feynman')"><MessageCircle :size="17" /><span>费曼复讲</span></button>
      <button type="button" @click="$emit('learn')"><BookOpenText :size="17" /><span>继续学习</span></button>
      <button type="button" @click="$emit('advanced')"><ArrowUpRight :size="17" /><span>进阶训练</span></button>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowLeft, ArrowUpRight, BookOpenText, MessageCircle, SquareCheck } from 'lucide-vue-next'
import GrowthTree from '@/features/fundamentals/GrowthTree.vue'

const props = defineProps({
  node: { type: Object, required: true },
  latestScoreLabel: { type: String, default: '--' },
  answerSummary: { type: String, default: '' },
  masteryLabel: { type: String, default: '--' },
  masteryValue: { type: Number, default: 0 },
  masteryEvidence: { type: String, default: '' },
  weakPoints: { type: Array, default: () => [] },
  nextSuggestionTitle: { type: String, default: '' },
  nextSuggestionReason: { type: String, default: '' },
  /**
   * 能不能开费曼复讲。**和"能不能做题"是两件事，别合并。**
   * 复讲要拿本章正文当底稿，一份资料没读过的章节没有正文，开了是空讲。
   * 「题目测试」相反 —— 题是现场从章节主题生成的，任何章节都能测（见 FoundationTestPage）。
   */
  canFeynman: { type: Boolean, default: false },
})

defineEmits(['back', 'quiz', 'feynman', 'learn', 'advanced'])

// 这里原本还有一份 `stage` —— 和 StudyGarden 里那份逐字重复，两边各判一次"第几档"。
// 树形现在完全由 GrowthTree 从 node 推出来，不需要中间那层档位了。
const weakPointLabel = computed(() => props.weakPoints.length ? props.weakPoints.slice(0, 2).map((point) => point.tag).join('、') : '完成答题后自动记录')
</script>

<style scoped>
.tree-review { position: relative; min-height: 560px; overflow: hidden; isolation: isolate; margin-bottom: 16px; border: 1px solid #d8e4d5; border-radius: 7px; background: #edf5e9; color: #244238; }
.tree-review__sun { position: absolute; z-index: -4; top: 42px; right: 12%; width: 88px; height: 88px; border-radius: 50%; background: #efd883; opacity: .74; }.tree-review__cloud { position: absolute; z-index: -4; width: 93px; height: 19px; border-radius: 50%; background: #fff; opacity: .62; }.tree-review__cloud::before,.tree-review__cloud::after { position: absolute; bottom: 0; border-radius: 50%; background: inherit; content: ''; }.tree-review__cloud::before { left: 18px; width: 32px; height: 32px; }.tree-review__cloud::after { right: 14px; width: 39px; height: 25px; }.tree-review__cloud--left { top: 98px; left: 12%; }.tree-review__cloud--right { top: 158px; right: 25%; transform: scale(.65); }
.tree-review__hill { position: absolute; z-index: -3; right: -8%; left: -8%; border-radius: 50% 50% 0 0; }.tree-review__hill--back { bottom: 20%; height: 47%; background: #c7dfbf; transform: rotate(-3deg); }.tree-review__hill--front { bottom: -19%; height: 57%; background: #a6ca9c; transform: rotate(2deg); }/* 这条"小径"往左挪开：树在这版里宽了（255px → 360px），原来它正好压在树底下，
   看着像树站在一滩沙里。挪到左边反而读成"一条通向那棵树的路"。 */
.tree-review__path { position: absolute; z-index: -2; bottom: -20%; left: 23%; width: 17%; height: 58%; background: linear-gradient(100deg, rgba(188,148,98,.5), rgba(226,203,161,.75) 50%, rgba(186,143,94,.45)); clip-path: polygon(43% 0, 57% 0, 100% 100%, 0 100%); transform: rotate(3deg); opacity: .6; }
.tree-review__grass { position: absolute; z-index: -1; bottom: 13%; width: 76px; height: 38px; border-right: 3px solid #63955e; border-radius: 0 100% 0 0; transform: skewX(-22deg); opacity: .65; }.tree-review__grass::after { position: absolute; right: 14px; bottom: -7px; width: 56px; height: 31px; border-right: 3px solid #63955e; border-radius: 0 100% 0 0; content: ''; }.tree-review__grass--one { left: 15%; }.tree-review__grass--two { right: 14%; transform: scaleX(-1) skewX(-22deg); }
.tree-review__back { position: absolute; top: 18px; left: 20px; display: inline-flex; align-items: center; gap: 5px; padding: 0; border: 0; background: transparent; color: #4b714b; cursor: pointer; font-size: 11px; font-weight: 800; }.tree-review__back:hover { color: #254e34; }.tree-review__back:focus-visible,.tree-review__actions button:focus-visible { outline: 2px solid #527a50; outline-offset: 4px; }
.tree-review__heading { position: absolute; top: 65px; left: 7%; max-width: min(360px, 36%); }.tree-review__heading .eyebrow { margin: 0 0 7px; color: #638062; font-size: 10px; }.tree-review__heading h2 { margin: 0; color: #244238; font-size: 22px; line-height: 1.32; }.tree-review__heading p:last-child { margin: 7px 0 0; color: #607b6b; font-size: 11px; line-height: 1.65; }
/* 高度不写死：GrowthTree 按 viewBox 的宽高比自己撑开，宿主只给宽度。 */
.tree-review__tree { position: absolute; bottom: 4%; left: 50%; width: 360px; transform: translateX(-50%); }
.tree-review__data { position: absolute; display: grid; gap: 4px; max-width: 175px; padding-left: 11px; border-left: 2px solid #80a866; }.tree-review__data > span { color: #547250; font-size: 10px; font-weight: 800; }.tree-review__data strong { overflow: hidden; color: #244238; font-size: 25px; line-height: 1.1; text-overflow: ellipsis; white-space: nowrap; }.tree-review__data small { overflow: hidden; color: #607b6b; font-size: 10px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }.tree-review__data--score { top: 275px; left: 8%; }.tree-review__data--mastery { top: 86px; right: 7%; }.tree-review__data--weakness { right: 8%; bottom: 155px; }.tree-review__data--next { right: 8%; bottom: 72px; max-width: 220px; }.tree-review__data--next strong { font-size: 13px; }.tree-review__data--mastery i { display: block; width: 145px; height: 5px; overflow: hidden; border-radius: 999px; background: #dce8d7; }.tree-review__data--mastery b { display: block; height: 100%; border-radius: inherit; background: #8eaf57; transition: width 400ms ease; }
.tree-review__actions { position: absolute; z-index: 2; bottom: 27px; left: 50%; display: flex; flex-wrap: wrap; justify-content: center; gap: 13px; max-width: calc(100% - 32px); transform: translateX(-50%); }.tree-review__actions button { display: inline-flex; align-items: center; gap: 7px; min-height: 34px; padding: 0 8px; border: 0; border-bottom: 2px solid #6c995d; background: transparent; color: #31543a; cursor: pointer; font-size: 12px; font-weight: 800; white-space: nowrap; }.tree-review__actions button:hover { border-color: #31543a; color: #173c2c; transform: translateY(-2px); }
@media (max-width: 760px) { .tree-review { min-height: 740px; }.tree-review__heading { max-width: 62%; }.tree-review__tree { bottom: 155px; width: 260px; }.tree-review__data--score { top: 245px; left: 7%; }.tree-review__data--mastery { top: 98px; right: 6%; }.tree-review__data--weakness { right: 7%; bottom: 96px; }.tree-review__data--next { bottom: 23px; left: 7%; right: auto; max-width: 45%; }.tree-review__actions { bottom: 148px; }.tree-review__sun { width: 62px; height: 62px; } }
@media (max-width: 500px) { .tree-review { min-height: 790px; }.tree-review__heading { top: 58px; left: 18px; max-width: calc(100% - 36px); }.tree-review__heading h2 { font-size: 19px; }.tree-review__tree { bottom: 216px; width: 205px; height: 270px; }.tree-review__data { max-width: 43%; }.tree-review__data--score { top: 225px; left: 18px; }.tree-review__data--mastery { top: 225px; right: 18px; }.tree-review__data--weakness { right: 18px; bottom: 106px; }.tree-review__data--next { bottom: 30px; left: 18px; max-width: 48%; }.tree-review__actions { bottom: 180px; gap: 8px; }.tree-review__actions button { font-size: 11px; }.tree-review__cloud { display: none; } }
</style>

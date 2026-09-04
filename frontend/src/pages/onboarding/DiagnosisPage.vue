<template>
  <div class="onboarding-page">
    <PageTitle eyebrow="能力诊断" title="先测出你的起点" description="用 3 道小题校准学习起点，系统会据此调整讲解深度和练习难度。" />
    <section class="surface surface-pad diagnosis-card">
      <div class="diagnosis-meta"><span>第 {{ currentIndex + 1 }} / {{ questions.length }} 题</span><div class="progress-track"><div class="progress-value" :style="{ width: `${progress}%` }"></div></div></div>
      <h2>{{ currentQuestion.title }}</h2><p class="question-context">{{ currentQuestion.context }}</p>
      <div class="answer-list"><button v-for="answer in currentQuestion.answers" :key="answer" class="answer-option" :class="{ selected: selectedAnswer === answer }" type="button" @click="selectedAnswer = answer"><span class="answer-dot"></span>{{ answer }}</button></div>
      <div class="diagnosis-actions"><button class="button button--primary" type="button" :disabled="!selectedAnswer" @click="next">{{ currentIndex === questions.length - 1 ? '查看诊断结果' : '下一题' }} <span>→</span></button></div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { diagnosisQuestions as questions } from '@/features/diagnosis/diagnosisQuestions'

const router = useRouter(); const currentIndex = ref(0); const selectedAnswer = ref('')
const currentQuestion = computed(() => questions[currentIndex.value]); const progress = computed(() => ((currentIndex.value + 1) / questions.length) * 100)
function next() { if (!selectedAnswer.value) return; if (currentIndex.value < questions.length - 1) { currentIndex.value += 1; selectedAnswer.value = '' } else router.push('/onboarding/diagnosis/result') }
</script>

<style scoped>
.onboarding-page { max-width: 760px; margin: 0 auto; }.diagnosis-card { padding: clamp(22px, 4vw, 42px); }.diagnosis-meta { display: flex; align-items: center; gap: 14px; color: var(--muted); font-size: 12px; }.diagnosis-meta .progress-track { flex: 1; }.diagnosis-card h2 { margin: 38px 0 8px; font-size: clamp(22px, 3vw, 30px); }.question-context { margin: 0 0 25px; color: var(--muted); font-size: 13px; }.answer-list { display: grid; gap: 10px; }.answer-option { display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 0 15px; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); text-align: left; font-size: 13px; }.answer-option:hover, .answer-option.selected { border-color: var(--accent-deep); background: #f8fbf2; }.answer-dot { width: 13px; height: 13px; border: 1px solid #aeb8ad; border-radius: 50%; }.selected .answer-dot { border: 4px solid var(--accent-deep); }.diagnosis-actions { display: flex; justify-content: flex-end; margin-top: 30px; }.button:disabled { cursor: not-allowed; opacity: .45; }
</style>

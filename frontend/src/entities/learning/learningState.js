import { reactive } from 'vue'

export const learningState = reactive({
  identity: localStorage.getItem('learnmate_identity') || '',
  direction: localStorage.getItem('learnmate_direction') || '智能系统与知识工程',
  goal: localStorage.getItem('learnmate_goal') || '完成一个可验证的项目',
  mastery: { rag: 41, agent: 28, evaluation: 36 },
})

export function persistLearningProfile() {
  localStorage.setItem('learnmate_identity', learningState.identity)
  localStorage.setItem('learnmate_direction', learningState.direction)
  localStorage.setItem('learnmate_goal', learningState.goal)
}

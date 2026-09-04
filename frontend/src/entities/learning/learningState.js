import { reactive } from 'vue'

export const learningState = reactive({
  identity: localStorage.getItem('learnmate_identity') || '',
  direction: localStorage.getItem('learnmate_direction') || '',
  goal: localStorage.getItem('learnmate_goal') || '',
})

export function persistLearningProfile() {
  localStorage.setItem('learnmate_identity', learningState.identity)
  localStorage.setItem('learnmate_direction', learningState.direction)
  localStorage.setItem('learnmate_goal', learningState.goal)
}

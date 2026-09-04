<template>
  <main class="identity-page">
    <div class="identity-wash" aria-hidden="true"></div>
    <div class="identity-word" aria-hidden="true">
      <span>LEARN</span>
      <span>MATE</span>
    </div>
    <router-link class="back-link" to="/">
      <span aria-hidden="true">←</span>
      <span>BACK</span>
    </router-link>

    <section class="identity-panel" aria-labelledby="identity-title">
      <h1 id="identity-title">完成学习定向</h1>

      <div class="direction-fields">
        <label class="direction-field">
          <span>你的学习方向</span>
          <select v-model="selectedDirection">
            <option v-for="option in directionOptions" :key="option" :value="option">{{ option }}</option>
          </select>
          <input
            v-model.trim="customDirection"
            type="text"
            maxlength="80"
            placeholder="或输入自定义学习方向"
            aria-label="自定义学习方向"
          />
        </label>
        <label class="direction-field">
          <span>你希望达成什么</span>
          <select v-model="selectedGoal">
            <option v-for="option in goalOptions" :key="option" :value="option">{{ option }}</option>
          </select>
          <input
            v-model.trim="customGoal"
            type="text"
            maxlength="120"
            placeholder="或输入自定义目标"
            aria-label="自定义学习目标"
          />
        </label>
      </div>

      <div class="identity-grid" role="radiogroup" aria-label="Choose your identity">
        <button
          v-for="option in identityOptions"
          :key="option"
          class="identity-option"
          :class="{ selected: selectedIdentity === option }"
          type="button"
          role="radio"
          :aria-checked="selectedIdentity === option"
          @click="selectedIdentity = option"
        >
          <span class="option-label">{{ option }}</span>
        </button>
      </div>

      <div class="identity-actions">
        <button class="continue-button" type="button" :disabled="!canContinue" @click="continueToStudy">
          <span>CONTINUE</span>
          <span aria-hidden="true">↗</span>
        </button>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { directionOptions, goalOptions } from '@/features/onboarding/onboardingOptions'
import { learningState, persistLearningProfile } from '@/entities/learning/learningState'

const router = useRouter()
const selectedIdentity = ref(localStorage.getItem('learnmate_identity') || '')
const storedDirection = localStorage.getItem('learnmate_direction') || ''
const storedGoal = localStorage.getItem('learnmate_goal') || ''
const selectedDirection = ref(directionOptions.includes(storedDirection) ? storedDirection : directionOptions[0])
const selectedGoal = ref(goalOptions.includes(storedGoal) ? storedGoal : goalOptions[0])
const customDirection = ref(directionOptions.includes(storedDirection) ? '' : storedDirection)
const customGoal = ref(goalOptions.includes(storedGoal) ? '' : storedGoal)
const resolvedDirection = computed(() => customDirection.value || selectedDirection.value)
const resolvedGoal = computed(() => customGoal.value || selectedGoal.value)
const canContinue = computed(() => Boolean(selectedIdentity.value && resolvedDirection.value && resolvedGoal.value))

const identityOptions = [
  '在校大学生',
  '高职 / 中职学生',
  '应届毕业生',
  '一线技术人员',
  '工程师 / 开发者',
  '产品 / 项目管理者',
  '教师 / 培训师',
  '企业管理者',
  '想转行的学习者',
  '自由职业者',
]

const continueToStudy = () => {
  if (!canContinue.value) return
  learningState.identity = selectedIdentity.value
  learningState.direction = resolvedDirection.value
  learningState.goal = resolvedGoal.value
  persistLearningProfile()
  window.dispatchEvent(new CustomEvent('learnmate:identity-selected', { detail: selectedIdentity.value }))
  router.push('/onboarding/diagnosis')
}
</script>

<style scoped>
@font-face {
  font-family: "Smiley Sans";
  src: url("../../shared/assets/fonts/SmileySans-Oblique.woff2") format("woff2");
  font-style: normal;
  font-display: swap;
}

.identity-page {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  isolation: isolate;
  padding: clamp(28px, 5vw, 64px) clamp(20px, 6vw, 90px) 56px;
  color: #f3f0e7;
  background: #1e3c34;
  font-family: Inter, "Helvetica Neue", Arial, sans-serif;
}

.identity-page::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -3;
  background:
    linear-gradient(120deg, rgba(3, 18, 13, 0.86) 0%, rgba(28, 68, 53, 0.68) 34%, rgba(5, 24, 17, 0.92) 68%, rgba(53, 93, 69, 0.56) 100%),
    radial-gradient(ellipse 80% 68% at 8% 92%, rgba(151, 184, 137, 0.5), transparent 66%),
    radial-gradient(ellipse 62% 62% at 92% 8%, rgba(2, 13, 10, 0.92), transparent 70%),
    #1e3c34;
  background-size: 180% 180%, 100% 100%, 100% 100%, 100% 100%;
  animation: metalShift 18s ease-in-out infinite alternate;
}

.identity-page::after {
  content: "";
  position: absolute;
  inset: -30%;
  z-index: -1;
  pointer-events: none;
  background: linear-gradient(112deg, transparent 30%, rgba(216, 239, 187, 0.08) 44%, rgba(255, 255, 255, 0.14) 48%, rgba(216, 239, 187, 0.04) 54%, transparent 68%);
  transform: translate3d(-18%, 0, 0) rotate(-3deg);
  animation: metalSheen 14s ease-in-out infinite alternate;
}

.identity-wash {
  position: absolute;
  inset: -18%;
  z-index: -1;
  pointer-events: none;
  opacity: 0.62;
  filter: blur(96px);
  background:
    radial-gradient(ellipse at 35% 30%, rgba(209, 239, 148, 0.34), transparent 46%),
    radial-gradient(ellipse at 72% 72%, rgba(82, 147, 104, 0.38), transparent 52%);
  animation: washDrift 12s ease-in-out infinite alternate;
}

.identity-word {
  position: absolute;
  inset: 8% 0 0;
  z-index: -2;
  display: grid;
  align-content: center;
  justify-items: center;
  color: rgba(173, 198, 178, 0.28);
  font-family: Georgia, "Times New Roman", serif;
  font-size: clamp(116px, 17.5vw, 282px);
  font-weight: 400;
  letter-spacing: -0.045em;
  line-height: 0.76;
  user-select: none;
  pointer-events: none;
}

.identity-word span {
  display: block;
  transform: scaleX(1.08);
}

.back-link {
  position: relative;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: rgba(243, 240, 231, 0.8);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.16em;
  text-decoration: none;
  transition: color 0.2s ease, transform 0.2s ease;
}

.back-link:hover {
  color: #e2f452;
  transform: translateX(-3px);
}

.back-link span:first-child {
  font-size: 20px;
  line-height: 0.6;
}

.identity-panel {
  width: 100%;
  margin: clamp(24px, 4vh, 48px) 0 0;
  animation: panelIn 0.8s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.identity-panel h1 {
  margin: 0;
  color: #f3f0e7;
  font-size: clamp(20px, 2.4vw, 30px);
  font-weight: 500;
  font-family: "Smiley Sans", Georgia, serif;
  letter-spacing: 0.04em;
  line-height: 1;
  text-align: left;
}

.direction-fields {
  width: min(700px, 100%);
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin: 28px auto 0;
}

.direction-field {
  display: grid;
  gap: 8px;
  color: rgba(243, 240, 231, 0.72);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.direction-field select {
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid rgba(243, 240, 231, 0.25);
  border-radius: 5px;
  background: rgba(10, 31, 22, 0.55);
  color: #f3f0e7;
  outline: none;
}

.direction-field input {
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid rgba(243, 240, 231, 0.2);
  border-radius: 5px;
  background: rgba(10, 31, 22, 0.34);
  color: #f3f0e7;
  outline: none;
}

.direction-field input::placeholder { color: rgba(243, 240, 231, 0.46); }
.direction-field select:focus,
.direction-field input:focus { border-color: #e2f452; }

.identity-grid {
  width: min(700px, 100%);
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 240px));
  justify-content: center;
  column-gap: 144px;
  row-gap: 40px;
  margin: 26px auto 0;
}

.identity-option {
  width: 100%;
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px 20px;
  border: 0;
  border-radius: 999px;
  background: #e2f452;
  color: #1e3c34;
  text-align: center;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(4, 20, 15, 0.18);
  transform: translateZ(0);
  transform-origin: center center;
  will-change: transform, box-shadow, background;
  transition: transform 0.58s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.58s cubic-bezier(0.16, 1, 0.3, 1), background 0.45s ease;
  animation: optionIn 0.6s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.identity-option:hover,
.identity-option.selected {
  background: #f8ff91;
  transform: translateY(-16px) scale(1.09);
  box-shadow: 0 30px 48px rgba(4, 20, 15, 0.44);
}

.identity-option:focus-visible,
.continue-button:focus-visible,
.back-link:focus-visible {
  outline: 3px solid #f3f0e7;
  outline-offset: 4px;
}

.identity-option.selected {
  box-shadow: 0 0 0 3px rgba(243, 240, 231, 0.9), 0 30px 48px rgba(4, 20, 15, 0.44);
}

.identity-option:hover {
  transform: translate3d(0, -22px, 0) scale(1.13);
  box-shadow: 0 34px 54px rgba(4, 20, 15, 0.48);
}

.identity-option.selected,
.identity-option[aria-checked="true"] {
  background: #b3f884 !important;
}

.option-label {
  min-width: 0;
  font-size: 18px;
  font-weight: 800;
  line-height: 1.35;
}

.identity-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 18px;
  margin-top: 30px;
}

.continue-button {
  min-height: 48px;
  display: inline-flex;
  align-items: center;
  gap: 13px;
  padding: 0 20px 0 22px;
  border: 0;
  border-radius: 5px;
  background: #e2f452;
  color: #1e3c34;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.13em;
  cursor: pointer;
  box-shadow: 0 12px 26px rgba(4, 20, 15, 0.28);
  transition: background 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.continue-button:hover:not(:disabled) {
  background: #f0ff75;
  transform: translateY(-2px);
  box-shadow: 0 16px 30px rgba(4, 20, 15, 0.38);
}

.continue-button:disabled {
  opacity: 0.42;
  cursor: not-allowed;
  box-shadow: none;
}

.continue-button span:last-child {
  font-size: 20px;
  line-height: 0.65;
}

.identity-option:nth-child(2) { animation-delay: 0.04s; }
.identity-option:nth-child(even) { animation-name: optionInRight; }
.identity-option:nth-child(3) { animation-delay: 0.08s; }
.identity-option:nth-child(4) { animation-delay: 0.12s; }
.identity-option:nth-child(5) { animation-delay: 0.16s; }
.identity-option:nth-child(6) { animation-delay: 0.2s; }
.identity-option:nth-child(7) { animation-delay: 0.24s; }
.identity-option:nth-child(8) { animation-delay: 0.28s; }
.identity-option:nth-child(9) { animation-delay: 0.32s; }
.identity-option:nth-child(10) { animation-delay: 0.36s; }

@keyframes panelIn {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes optionIn {
  from { opacity: 0; transform: translate3d(-46px, 16px, 0) scale(0.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes optionInRight {
  from { opacity: 0; transform: translate3d(46px, 16px, 0) scale(0.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes washDrift {
  from { transform: translate3d(-3%, -2%, 0) scale(0.98); }
  to { transform: translate3d(3%, 2%, 0) scale(1.04); }
}

@keyframes metalShift {
  from { background-position: 0% 50%, 0 0, 0 0, 0 0; filter: saturate(0.94) contrast(1.02); }
  to { background-position: 100% 50%, 0 0, 0 0, 0 0; filter: saturate(1.1) contrast(1.08); }
}

@keyframes metalSheen {
  from { transform: translate3d(-18%, 0, 0) rotate(-3deg); opacity: 0.45; }
  to { transform: translate3d(18%, 0, 0) rotate(-3deg); opacity: 0.88; }
}

@media (max-width: 640px) {
  .identity-page {
    padding: 26px 18px 34px;
  }

  .identity-panel {
    margin-top: 34px;
  }

  .direction-fields {
    grid-template-columns: 1fr;
  }

  .identity-grid {
    grid-template-columns: 1fr;
    width: min(260px, 100%);
    gap: 24px;
  }

  .identity-option {
    min-height: 50px;
  }

  .identity-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .continue-button {
    justify-content: center;
  }
}

@media (prefers-reduced-motion: reduce) {
  .identity-page::before,
  .identity-wash,
  .identity-panel,
  .back-link,
  .identity-option,
  .continue-button {
    animation: none !important;
    transition-duration: 0.01ms !important;
  }
}
</style>

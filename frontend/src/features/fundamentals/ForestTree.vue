<template>
  <svg class="forest-tree" :class="[`forest-tree--${variant}`, `forest-tree--stage-${stage}`]" viewBox="0 0 180 220" role="img" :aria-label="label">
    <defs>
      <filter :id="filterId" x="-16%" y="-12%" width="132%" height="128%">
        <feTurbulence type="fractalNoise" baseFrequency=".55" numOctaves="2" seed="19" result="grain" />
        <feDisplacementMap in="SourceGraphic" in2="grain" scale="1.2" xChannelSelector="R" yChannelSelector="G" />
      </filter>
      <linearGradient :id="soilGradientId" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#c79465" />
        <stop offset="1" stop-color="#936040" />
      </linearGradient>
      <linearGradient :id="trunkGradientId" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#75492f" />
        <stop offset=".48" stop-color="#a56d47" />
        <stop offset="1" stop-color="#68432e" />
      </linearGradient>
      <radialGradient :id="leafGradientId" cx="42%" cy="28%" r="78%">
        <stop offset="0" stop-color="#83ad6f" />
        <stop offset=".65" stop-color="#5d8f57" />
        <stop offset="1" stop-color="#3f7049" />
      </radialGradient>
      <radialGradient :id="leafHighlightGradientId" cx="35%" cy="20%" r="90%">
        <stop offset="0" stop-color="#b0cd92" />
        <stop offset="1" stop-color="#76a166" />
      </radialGradient>
    </defs>
    <g class="forest-tree__art" :filter="`url(#${filterId})`">
      <ellipse class="forest-tree__shadow" cx="91" cy="193" rx="64" ry="8" />
      <path class="forest-tree__soil" :fill="`url(#${soilGradientId})`" d="M21 191C38 170 61 169 89 177C111 164 145 170 160 191C143 202 50 205 21 191Z" />
      <path v-if="stage >= 1" class="forest-tree__stem" :class="{ 'forest-tree__stem--sprout': stage === 1 }" :d="stemPath" />
      <path v-if="stage === 1" class="forest-tree__leaf forest-tree__leaf--one" d="M92 113C68 105 52 84 62 66C80 60 93 84 92 113Z" />
      <path v-if="stage === 1" class="forest-tree__leaf forest-tree__leaf--two" d="M93 111C99 80 119 59 139 68C145 88 119 108 93 111Z" />
      <path v-if="stage === 1" class="forest-tree__sprout-vein" d="M93 112L65 72M93 112L135 73" />
      <template v-if="stage === 2">
        <path class="forest-tree__branch" d="M91 171C80 161 76 149 77 136M92 159C104 150 109 139 108 126" />
        <path class="forest-tree__leaf forest-tree__leaf--left" d="M78 143C61 130 52 139 57 151C66 158 75 153 78 143Z" />
        <path class="forest-tree__leaf forest-tree__leaf--right" d="M106 129C120 115 133 123 130 137C120 145 111 140 106 129Z" />
        <path class="forest-tree__leaf forest-tree__leaf--one" d="M88 151C77 143 69 149 72 158C79 164 85 160 88 151Z" />
      </template>
      <template v-if="stage >= 3">
        <path class="forest-tree__branch" d="M90 151C77 139 72 127 70 112M93 139C109 128 115 115 115 102" />
        <path class="forest-tree__leaf forest-tree__leaf--left" d="M72 119C53 104 43 115 50 130C61 137 70 130 72 119Z" />
        <path class="forest-tree__leaf forest-tree__leaf--right" d="M113 108C130 91 144 102 139 119C127 128 117 120 113 108Z" />
      </template>
      <template v-if="stage === 3">
        <path class="forest-tree__crown forest-tree__crown--main" :fill="`url(#${leafGradientId})`" d="M92 76C113 75 126 90 119 106C130 119 119 136 102 132C92 144 73 137 72 124C54 120 51 102 63 94C61 82 76 73 92 76Z" />
        <path class="forest-tree__crown forest-tree__crown--light" :fill="`url(#${leafHighlightGradientId})`" d="M78 88C87 80 101 83 104 94C96 102 84 101 78 88Z" />
      </template>
      <template v-if="stage >= 4">
        <path class="forest-tree__crown forest-tree__crown--main" :fill="`url(#${leafGradientId})`" d="M91 47C121 45 139 63 130 87C146 103 133 128 109 125C99 142 73 139 67 121C42 118 35 95 52 81C48 59 67 42 91 47Z" />
        <path class="forest-tree__crown forest-tree__crown--light" :fill="`url(#${leafHighlightGradientId})`" d="M73 62C84 49 105 53 108 68C99 80 81 79 73 62Z" />
        <path class="forest-tree__crown forest-tree__crown--top" :fill="`url(#${leafHighlightGradientId})`" d="M91 24C110 22 125 35 119 52C110 61 93 59 84 50C78 37 82 27 91 24Z" />
        <path class="forest-tree__crown forest-tree__crown--side" :fill="`url(#${leafGradientId})`" d="M45 94C52 77 72 76 80 91C86 108 71 120 55 113C43 111 39 102 45 94Z" />
        <path class="forest-tree__crown forest-tree__crown--side forest-tree__crown--right" :fill="`url(#${leafGradientId})`" d="M113 93C126 77 146 81 151 96C155 110 140 120 126 114C113 112 106 102 113 93Z" />
        <circle class="forest-tree__fruit" cx="67" cy="100" r="3" />
        <circle class="forest-tree__fruit" cx="117" cy="83" r="3" />
        <circle class="forest-tree__fruit" cx="104" cy="110" r="2.5" />
      </template>
      <ellipse v-if="stage === 0" class="forest-tree__seed" cx="91" cy="183" rx="7" ry="5" transform="rotate(-28 91 183)" />
    </g>
  </svg>
</template>

<script setup>
import { computed } from 'vue'

let forestTreeUid = 0

const props = defineProps({
  stage: { type: Number, default: 0 },
  variant: { type: String, default: 'round' },
  label: { type: String, default: '学习树' },
})

const instanceId = ++forestTreeUid
const filterId = computed(() => `forest-tree-texture-${instanceId}-${props.variant}-${props.stage}`)
const soilGradientId = computed(() => `forest-tree-soil-${instanceId}`)
const trunkGradientId = computed(() => `forest-tree-trunk-${instanceId}`)
const leafGradientId = computed(() => `forest-tree-leaf-${instanceId}`)
const leafHighlightGradientId = computed(() => `forest-tree-leaf-highlight-${instanceId}`)
const stemPath = computed(() => props.stage >= 4
  ? 'M91 184C88 159 95 129 90 95C93 126 103 142 115 151M91 143C81 130 75 121 73 105'
  : props.stage >= 2
    ? 'M91 184C89 160 94 133 91 105'
    : 'M91 186C88 154 95 121 93 99')
</script>

<style scoped>
.forest-tree { display: block; width: 100%; height: 100%; overflow: visible; }
.forest-tree__art { transform-box: fill-box; transform-origin: 50% 100%; animation: forest-tree-enter 620ms cubic-bezier(.18,.78,.26,1.12) both, forest-tree-breeze 4.8s 720ms ease-in-out infinite; }
.forest-tree__shadow { fill: #5d754f; opacity: .2; filter: blur(2px); }.forest-tree__soil { fill: #b88158; }.forest-tree__seed { fill: #8b5b39; }.forest-tree__stem,.forest-tree__branch { fill: none; stroke: #87593c; stroke-linecap: round; stroke-linejoin: round; stroke-width: 7; }.forest-tree__stem--sprout { stroke: #4c9651; stroke-width: 3.5; }.forest-tree__branch { stroke-width: 4; }.forest-tree__sprout-vein { fill: none; stroke: #5d9b56; stroke-linecap: round; stroke-width: 1.25; opacity: .72; }
.forest-tree__leaf { fill: #80aa70; transform-box: fill-box; transform-origin: 50% 100%; animation: forest-leaf-unfold 500ms 180ms ease-out both; }.forest-tree__leaf--two,.forest-tree__leaf--right { fill: #67955e; }.forest-tree__crown { fill: #5c9159; transform-box: fill-box; transform-origin: 50% 100%; animation: forest-crown-breathe 3.8s 700ms ease-in-out infinite; }.forest-tree__crown--light { fill: #88b67b; }.forest-tree__crown--top { fill: #78a86b; animation-delay: 1.8s; }.forest-tree__crown--side { fill: #6da567; animation-delay: 1.1s; }.forest-tree__crown--right { fill: #4f8250; animation-delay: 1.5s; }.forest-tree__fruit { fill: #e5b25d; transform-box: fill-box; transform-origin: center; animation: forest-fruit-pop 500ms 420ms cubic-bezier(.18,.78,.26,1.12) both; }
.forest-tree--pine .forest-tree__crown--main { fill: #3f7652; }.forest-tree--pine .forest-tree__crown--side { fill: #527f5e; }.forest-tree--willow .forest-tree__crown--main { fill: #6f9c6b; }.forest-tree--willow .forest-tree__crown--light { fill: #a1c58e; }
.forest-tree--stage-0 .forest-tree__art { animation: none; }.forest-tree--stage-0 .forest-tree__soil { animation: forest-soil-settle 420ms ease-out both; }
@keyframes forest-tree-enter { from { opacity: 0; transform: translateY(17px) scale(.52); } 72% { opacity: 1; transform: translateY(-2px) scale(1.04); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes forest-tree-breeze { 0%,100% { transform: rotate(-.65deg); } 50% { transform: rotate(1.05deg); } }
@keyframes forest-leaf-unfold { from { opacity: 0; transform: scale(.22) rotate(-14deg); } to { opacity: 1; transform: scale(1) rotate(0); } }
@keyframes forest-crown-breathe { 0%,100% { transform: scale(1); } 50% { transform: scale(1.025); } }
@keyframes forest-fruit-pop { from { opacity: 0; transform: scale(0); } to { opacity: 1; transform: scale(1); } }
@keyframes forest-soil-settle { from { opacity: 0; transform: translateY(8px) scaleX(.68); } to { opacity: 1; transform: translateY(0) scaleX(1); } }
@media (prefers-reduced-motion: reduce) { .forest-tree__art,.forest-tree__leaf,.forest-tree__crown,.forest-tree__fruit,.forest-tree__soil { animation: none; } }
</style>

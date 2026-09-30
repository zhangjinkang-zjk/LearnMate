<template>
  <svg class="forest-tree" :class="`forest-tree--${variant}`" viewBox="0 0 180 220" role="img" :aria-label="label">
    <defs>
      <filter :id="filterId" x="-16%" y="-12%" width="132%" height="128%">
        <feTurbulence type="fractalNoise" baseFrequency=".55" numOctaves="2" seed="19" result="grain" />
        <feDisplacementMap in="SourceGraphic" in2="grain" scale="1.2" xChannelSelector="R" yChannelSelector="G" />
      </filter>
    </defs>
    <g :filter="`url(#${filterId})`">
      <path class="forest-tree__soil" d="M21 191C38 170 61 169 89 177C111 164 145 170 160 191C143 202 50 205 21 191Z" />
      <path v-if="stage >= 1" class="forest-tree__stem" :d="stemPath" />
      <path v-if="stage === 1" class="forest-tree__leaf forest-tree__leaf--one" d="M91 150C76 139 66 144 68 156C77 164 86 160 91 150Z" />
      <path v-if="stage === 1" class="forest-tree__leaf forest-tree__leaf--two" d="M93 149C105 136 119 143 117 155C108 163 98 160 93 149Z" />
      <template v-if="stage >= 2">
        <path class="forest-tree__branch" d="M90 151C77 139 72 127 70 112M93 139C109 128 115 115 115 102" />
        <path class="forest-tree__leaf forest-tree__leaf--left" d="M72 119C53 104 43 115 50 130C61 137 70 130 72 119Z" />
        <path class="forest-tree__leaf forest-tree__leaf--right" d="M113 108C130 91 144 102 139 119C127 128 117 120 113 108Z" />
      </template>
      <template v-if="stage >= 3">
        <path class="forest-tree__crown forest-tree__crown--main" d="M91 47C121 45 139 63 130 87C146 103 133 128 109 125C99 142 73 139 67 121C42 118 35 95 52 81C48 59 67 42 91 47Z" />
        <path class="forest-tree__crown forest-tree__crown--light" d="M73 62C84 49 105 53 108 68C99 80 81 79 73 62Z" />
      </template>
      <template v-if="stage >= 4">
        <path class="forest-tree__crown forest-tree__crown--side" d="M45 94C52 77 72 76 80 91C86 108 71 120 55 113C43 111 39 102 45 94Z" />
        <path class="forest-tree__crown forest-tree__crown--side forest-tree__crown--right" d="M113 93C126 77 146 81 151 96C155 110 140 120 126 114C113 112 106 102 113 93Z" />
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
const stemPath = computed(() => props.stage >= 4
  ? 'M91 184C88 159 95 129 90 95C93 126 103 142 115 151M91 143C81 130 75 121 73 105'
  : props.stage >= 2
    ? 'M91 184C89 160 94 133 91 105'
    : 'M91 184C91 171 91 158 92 148')
</script>

<style scoped>
.forest-tree { display: block; width: 100%; height: 100%; overflow: visible; }
.forest-tree__soil { fill: #b88158; }.forest-tree__seed { fill: #8b5b39; }.forest-tree__stem,.forest-tree__branch { fill: none; stroke: #916140; stroke-linecap: round; stroke-linejoin: round; stroke-width: 7; }.forest-tree__branch { stroke-width: 4; }
.forest-tree__leaf { fill: #80aa70; }.forest-tree__leaf--two,.forest-tree__leaf--right { fill: #67955e; }.forest-tree__crown { fill: #5c9159; }.forest-tree__crown--light { fill: #88b67b; }.forest-tree__crown--side { fill: #6da567; }.forest-tree__crown--right { fill: #4f8250; }.forest-tree__fruit { fill: #e5b25d; }
.forest-tree--pine .forest-tree__crown--main { fill: #3f7652; }.forest-tree--pine .forest-tree__crown--side { fill: #527f5e; }.forest-tree--willow .forest-tree__crown--main { fill: #6f9c6b; }.forest-tree--willow .forest-tree__crown--light { fill: #a1c58e; }
</style>

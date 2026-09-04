<template>
  <div class="page-heading">
    <div>
      <p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <p v-if="description">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="page-actions"><slot name="actions" /></div>
  </div>
</template>

<script setup>
defineProps({ eyebrow: { type: String, default: 'LearnMate' }, title: { type: String, required: true }, description: { type: String, default: '' } })
</script>

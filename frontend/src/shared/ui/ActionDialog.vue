<template>
  <Teleport to="body">
    <dialog ref="dialog" class="action-dialog" :aria-label="title" @cancel="cancel" @close="emit('close')">
      <header><h2>{{ title }}</h2><button type="button" :disabled="busy" aria-label="关闭对话框" @click="dialog.close()">×</button></header>
      <slot />
    </dialog>
  </Teleport>
</template>
<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
const props = defineProps({ title: { type: String, required: true }, busy: Boolean })
const emit = defineEmits(['close'])
const dialog = ref(null)
const previousFocus = document.activeElement
function cancel(event) { if (props.busy) event.preventDefault() }
onMounted(() => dialog.value.showModal())
onBeforeUnmount(() => previousFocus?.focus?.())
</script>
<style scoped>
.action-dialog { width:min(820px, calc(100% - 28px)); max-height:88dvh; padding:24px; border:1px solid var(--line); border-radius:12px; background:var(--paper); color:var(--ink); box-shadow:0 24px 80px #102b2533; overflow:auto; }
.action-dialog::backdrop { background:#102b2577; }
header { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; margin-bottom:22px; }
h2 { margin:0; font-size:22px; overflow-wrap:anywhere; }
header button { flex-shrink:0; border:0; background:var(--soft); color:var(--ink); border-radius:6px; width:32px; height:32px; font-size:24px; }
button:focus-visible { outline:2px solid var(--accent-deep); outline-offset:3px; }
button:disabled { opacity:.5; cursor:wait; }
@media(max-width:560px) { .action-dialog { padding:18px; } }
</style>

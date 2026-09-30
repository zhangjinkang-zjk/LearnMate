<template>
  <div class="code-editor">
    <div v-if="loadError" class="code-editor__state code-editor__state--error">{{ loadError }}</div>
    <div v-else-if="!ready" class="code-editor__state"><LoaderCircle class="spin" :size="14" />正在装载编辑器…</div>
    <div ref="host" class="code-editor__host"></div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { LoaderCircle } from 'lucide-vue-next'
import { languageForPath, loadMonaco } from './monacoSetup'

const props = defineProps({
  modelValue: { type: String, default: '' },
  path: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'save'])

const host = ref(null)
const ready = ref(false)
const loadError = ref('')
let editor = null
let monacoRef = null
let resizeObserver = null
// 编辑器自己触发的变更不要再写回去，否则每次输入都会把光标顶到行尾
let applyingExternal = false

// 主题走现有设计变量，不引 monaco 自带的 vs/vs-dark —— 那套配色和 LearnMate 的
// 绿灰体系放在一起会像两个产品。色值取自 shared/styles/main.css 的 :root。
const THEME_NAME = 'learnmate'

function defineTheme(monaco) {
  monaco.editor.defineTheme(THEME_NAME, {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '6c7770', fontStyle: 'italic' },
      { token: 'keyword', foreground: '3f5b31', fontStyle: 'bold' },
      { token: 'string', foreground: '7a5c1e' },
      { token: 'number', foreground: '3f5b31' },
      { token: 'type', foreground: '1e3c34' },
      { token: 'function', foreground: '1e3c34' },
    ],
    colors: {
      'editor.background': '#ffffff',
      'editor.foreground': '#202824',
      'editorLineNumber.foreground': '#b3bcb4',
      'editorLineNumber.activeForeground': '#6c7770',
      'editor.lineHighlightBackground': '#f4f8ed',
      'editor.selectionBackground': '#dcecc0',
      'editorCursor.foreground': '#3f5b31',
      'editorIndentGuide.background1': '#eef1ee',
      'editorGutter.background': '#ffffff',
    },
  })
}

async function mountEditor() {
  const monaco = await loadMonaco()
  monacoRef = monaco
  if (!host.value) return
  defineTheme(monaco)
  editor = monaco.editor.create(host.value, {
    value: props.modelValue,
    language: languageForPath(props.path),
    theme: THEME_NAME,
    readOnly: props.readOnly,
    automaticLayout: false,
    fontSize: 13,
    lineHeight: 21,
    fontFamily: '"JetBrains Mono", "Cascadia Code", Consolas, "Microsoft YaHei", monospace',
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    renderLineHighlight: 'line',
    smoothScrolling: true,
    tabSize: 4,
    padding: { top: 12, bottom: 12 },
    scrollbar: { verticalScrollbarSize: 9, horizontalScrollbarSize: 9 },
  })
  editor.onDidChangeModelContent(() => {
    if (applyingExternal) return
    emit('update:modelValue', editor.getValue())
  })
  // Ctrl/Cmd+S 交给页面去决定存到哪里（磁盘还是下载），编辑器不该知道这件事
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => emit('save'))
  // automaticLayout 是轮询式的，容器一多就抖；自己听尺寸更稳
  resizeObserver = new ResizeObserver(() => editor?.layout())
  resizeObserver.observe(host.value)
  ready.value = true
}

watch(() => props.modelValue, (next) => {
  if (!editor || editor.getValue() === next) return
  applyingExternal = true
  editor.setValue(next ?? '')
  applyingExternal = false
})

watch(() => props.readOnly, (next) => editor?.updateOptions({ readOnly: next }))

// 切换文件：只换 model 的语言，不重建编辑器（重建会丢撤销栈和滚动位置）
watch(() => props.path, (next) => {
  if (!editor || !monacoRef) return
  const model = editor.getModel()
  if (model) monacoRef.editor.setModelLanguage(model, languageForPath(next))
})

mountEditor().catch((error) => { loadError.value = `编辑器加载失败：${error?.message || error}` })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  editor?.dispose()
  editor = null
})

defineExpose({
  focus: () => editor?.focus(),
})
</script>

<style scoped>
.code-editor { position: relative; min-width: 0; min-height: 0; height: 100%; background: var(--paper); }
.code-editor__host { height: 100%; }
.code-editor__state { display: flex; height: 100%; align-items: center; justify-content: center; gap: 7px; color: var(--muted); font-size: 12px; }
.code-editor__state--error { color: #954e38; padding: 0 20px; text-align: center; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>

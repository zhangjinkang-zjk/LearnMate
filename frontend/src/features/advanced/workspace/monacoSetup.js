// Monaco 的加载入口。三条约束都是实测出来的，改之前先看：
//
// 1. **worker 路径不能带 `esm/vs/`**。monaco 0.57 的 exports 映射是
//    `"./*.js": "./esm/vs/*.js"` —— 前缀已经注进去了，再照网上示例写
//    `monaco-editor/esm/vs/editor/editor.worker` 会拼成 `./esm/vs/esm/vs/...`，
//    Vite 8（Rolldown）直接构建失败。
// 2. **只引 editor.worker 就够**。ts.worker 一个 6.7MB，Python 用不到；引整个
//    `monaco-editor` 仍会带上语言服务 worker，要彻底去掉得窄引 `editor.api.js`。
// 3. **语言定义是懒加载的**：`register.js` 里是 `loader: () => import('./python.js')`。
//    所以编辑器刚挂载时立刻 tokenize 会拿到空数组 —— 那是时序问题，不是没注册成功。
//
// monaco 本体约 1.3MB，**只能动态 import**：静态引入会把主 chunk 从几百 KB 顶到 4MB。
//
// ⚠️ 连语言注册也必须是动态的。这些 register.js 会静态 import `editor.api.js`，
// 而本模块被 CodeEditor.vue 静态引入 —— 一旦这里写静态 `import '...register.js'`，
// 整棵 monaco 就被拽进主 chunk（实测主包从 692KB 涨到 3.4MB），动态 import 白做。
// 写在函数里而不是模块顶层：顶层的 import() 会在这个模块被求值时就发出请求，
// 等于用户还没点到编辑器就先下载 1.3MB。
function registerLanguages() {
  return Promise.all([
    import('monaco-editor/languages/definitions/python/register.js'),
    import('monaco-editor/languages/definitions/javascript/register.js'),
    import('monaco-editor/languages/definitions/typescript/register.js'),
    import('monaco-editor/languages/definitions/markdown/register.js'),
    import('monaco-editor/languages/definitions/yaml/register.js'),
    import('monaco-editor/languages/definitions/shell/register.js'),
    import('monaco-editor/languages/definitions/sql/register.js'),
    import('monaco-editor/languages/definitions/html/register.js'),
    import('monaco-editor/languages/definitions/css/register.js'),
    import('monaco-editor/languages/definitions/dockerfile/register.js'),
    import('monaco-editor/languages/definitions/ini/register.js'),
    import('monaco-editor/languages/definitions/xml/register.js'),
  ])
}

let monacoPromise = null

export function loadMonaco() {
  if (!monacoPromise) monacoPromise = createMonaco()
  return monacoPromise
}

async function createMonaco() {
  const [monaco, workerModule] = await Promise.all([
    // 窄引 editor.api 而不是 `monaco-editor`：主入口会把全部 84 种语言和
    // ts/json 语言服务一起静态拉进来（实测 2.7MB + 一堆用不上的语言 chunk）。
    // 高亮靠下面那几个 register.js 按需挂。
    import('monaco-editor/editor/editor.api.js'),
    import('monaco-editor/editor/editor.worker.js?worker'),
  ])
  const EditorWorker = workerModule.default
  // 必须在**创建编辑器之前**装好，编辑器实例化时就会去要 worker。
  self.MonacoEnvironment = { getWorker: () => new EditorWorker() }
  await registerLanguages()
  return monaco
}

// 后缀 → monaco 语言 id。选修课学员的项目里这几种占绝大多数，其余一律按纯文本打开
// （后面接代码批注智能体时，语言未知也不影响批注，只是没有语法着色）。
const LANGUAGE_BY_EXTENSION = {
  py: 'python',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  jsx: 'javascript',
  ts: 'typescript',
  vue: 'html',
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'css',
  md: 'markdown',
  markdown: 'markdown',
  yaml: 'yaml',
  yml: 'yaml',
  sh: 'shell',
  bash: 'shell',
  zsh: 'shell',
  sql: 'sql',
  ini: 'ini',
  cfg: 'ini',
  toml: 'ini',
  xml: 'xml',
  dockerfile: 'dockerfile',
}

export function languageForPath(path) {
  const name = String(path || '').split('/').pop() || ''
  if (name.toLowerCase() === 'dockerfile') return 'dockerfile'
  const extension = name.includes('.') ? name.split('.').pop().toLowerCase() : ''
  return LANGUAGE_BY_EXTENSION[extension] || 'plaintext'
}

# LearnMate 当前交接记录

更新时间：2026-09-05

## 当前分支与提交

- 分支：`main`
- 当前 HEAD：`56f6d31b`（已合并学习主流程与学习概览聚合接口）
- 当前工作区干净；后续改动请继续保留并行任务已合入的机器人功能。
- 最近前端合入：登录/注册弹窗、通知、计划本、个人信息、深色模式，以及基础讲解的多路径选择。

## 前端工程结构

前端目录为 `frontend/`，技术栈是 Vue 3、Vite、Vue Router、Axios、Lucide/Tailwind 相关现有依赖。

```text
frontend/src/
  app/                 # 应用入口、路由
  layouts/             # AppShell 等页面壳
  pages/               # 按业务页面组织
    home/
    onboarding/        # 学习定向、能力诊断、诊断结果
    learning/
    resources/
    settings/
  entities/            # 学习状态
  features/            # 诊断题目等业务数据
  shared/api/           # Axios API 封装
  shared/ui/            # 页面级公共 UI
  shared/styles/        # 全局样式
```

`App.vue` 根据路由 `meta.layout` 决定是否套用 `AppShell`：`immersive` 页面直接渲染，普通页面进入浅色学习工作区。

## 首次使用流程

当前业务顺序：

```text
学习定向 -> 能力诊断 -> 诊断结果确认 -> 学习概览
```

学习定向页面：

- 文件：`frontend/src/pages/onboarding/DirectionSetupPage.vue`
- 路由：`/onboarding/direction`
- 保留原有身份、学习方向、学习目标选择
- 学习方向和学习目标都支持自定义输入
- 点击 `CONTINUE` 后保存到 `learningState` 和 `localStorage`，跳转能力诊断

能力诊断页面：

- 文件：`frontend/src/pages/onboarding/DiagnosisPage.vue`
- 路由：`/onboarding/diagnosis`
- 当前已改成聊天记录式 UI
- 题目和判分由后端诊断会话接口负责，前端不保存正确答案
- 诊断流程固定 3 题，后端逐题按“概念理解 -> 应用排错 -> 迁移判断”生成

诊断结果页面：

- 文件：`frontend/src/pages/onboarding/DiagnosisResultPage.vue`
- 路由：`/onboarding/diagnosis/result`
- 读取 `localStorage.learnmate_diagnosis_result`，显示本次得分和后端建议

## 后端诊断接口

新增文件：

- `backend/src/router/diagnosis_router.py`
- `backend/src/service/diagnosis/service.py`
- `backend/src/ai_core/prompts/diagnosis.yaml`

接口：

- `POST /learning/diagnosis/start`
  - 参数：`identity`、`direction`、`goal`、`max_steps`
  - 创建会话，保存学习定向信息，生成第一道题
- `POST /learning/diagnosis/answer`
  - 参数：`session_id`、`question_id`、`answer`、`time_spent`、`max_steps`
  - 复用 `ExamService.submit_answer` 判分，更新 `ExamRecord`、`KnowledgeMastery` 和画像雷达，再生成下一题

后端接口都依赖 JWT 鉴权。前端通过 `/login` 调用既有 `/user/login_user` 获取 token，Axios 请求统一携带 `Authorization: Bearer <token>` 和兼容旧接口的 `token` header；路由守卫拦截未登录访问，接口返回 401 时清理 token 并回到登录页。

## 数据入库

学习定向信息写入 `user_picture.traits` 的 `onboarding` 节点，不新增数据库字段：

```json
{
  "onboarding": {
    "identity": "用户身份",
    "direction": "原始学习方向",
    "goal": "原始学习目标",
    "source": "user_stated"
  }
}
```

后端同时把目标映射到既有 `learning_goal` 枚举，供旧的画像、路径和资源逻辑使用；原始中文目标保留在 `traits.onboarding.goal`。

## 最近完成的改动

第二张图的绿色沉浸式背景已抽成公共组件，认证层也已接入既有 JWT 接口：

- 新增：`frontend/src/shared/ui/ImmersiveOnboardingBackdrop.vue`
- 修改：`DirectionSetupPage.vue` 使用公共背景组件
- 修改：`DiagnosisPage.vue` 迁移到同一绿色沉浸式背景
- 修改：`frontend/src/app/router/index.js` 将诊断和诊断结果标记为 `layout: immersive`

前端新增登录页、JWT 请求拦截器和路由守卫，学习定向、诊断和学习区均要求有效 token；Vite 开发代理已补充 `/learning`，可直接联调诊断接口。

当前工作区可能仍有其他任务产生的未跟踪文档，处理时不要删除或覆盖。

## 背景来源

第二张图的背景不是图片，原来完全来自 `DirectionSetupPage.vue` 的 CSS：

- `identity-page::before`
- `identity-page::after`
- `identity-wash`
- `identity-word`

迁移目标是只抽取这部分背景，保留各页面自己的内容布局，避免复制两套近似渐变。

## 验证与限制

- 前端最近一次 `npm run build` 已通过
- 后端 Python 文件最近一次 `py_compile` 已通过
- 当前环境未安装 `fastapi`，后端无法在本机启动做真实接口联调
- `docs/` 原本是未跟踪目录，里面的 `learnmate-function-and-backend-reference.md` 不要删除

## 多任务协作注意

多个 Codex 对话共享同一个工作区。可以并行，但不要同时修改同一文件。认证和规范改动涉及：

- `AGENTS.md`
- `frontend/src/app/router/index.js`
- `frontend/src/shared/api/httpClient.js`
- `frontend/src/shared/api/authApi.js`
- `frontend/src/pages/auth/LoginPage.vue`

## 2026-09-05 本次任务交接：学习主流程重组

本次实现状态：导航分组、基础测试、学习巩固页面以及进阶任务列表已完成；后端任务契约和课堂追问已同步。前端构建与后端针对性测试通过。

### 已确认的产品结构

用户已经确认基础讲解和进阶学习是两个不同的教学环节：

```text
学习概览
  ↓
知识学习组
  ├── 基础讲解：讲解文档知识、课堂追问
  └── 基础测试：题目测试、费曼反讲
  ↓
应用实践组
  ├── 进阶学习：根据掌握度和目标罗列实践任务
  └── 学习巩固：围绕任务进行连续追问，帮助用户逐步形成解决方案
  ↓
学习概览更新掌握度和下一步建议
```

基础讲解负责“理解知识”，基础测试负责“验证是否理解”；进阶学习负责“选择实践任务”，学习巩固负责“把知识应用到任务中”。不要把四者合并成一个泛化页面。

### 导航要求

侧边栏应使用分组视觉表达捆绑关系，不直接显示括号：

```text
学习
  学习概览

知识学习
  基础讲解
  基础测试

应用实践
  进阶学习
  学习巩固

工具
  资料库

我的
  设置
```

- 组标题是不可点击的分组标题；两个子项使用缩进、左侧连接线和阶段图标表达绑定关系。
- `学习工作区` 不放入全局导航。它是技术上的会话容器，用户从基础测试或进阶学习进入。
- `学习导航` 当前没有独立职责，不新增或保留一个只重复概览的页面；旧路由可以兼容重定向到 `/learning/overview`。
- 学习工作台/会话页内显示自己的局部步骤，不影响全局侧边栏。

### 页面任务

#### 1. 学习概览

文件：`frontend/src/pages/learning/OverviewPage.vue`

接口说明：见 [`docs/learning-overview-api.md`](./learning-overview-api.md)。页面接入时优先调用 `GET /study/overview`，不要在前端重复请求并拼接画像、路径和统计接口。

- 保留当前目标、学习方向、掌握度、薄弱点和系统决策。
- 增加两个阶段摘要：知识学习、应用实践；只显示当前状态和唯一下一步，不复制完整章节/任务列表。
- 显示暂停中的测试或巩固会话，并提供“继续”入口。
- `暂存退出` 的会话显示为“已暂停”，不能当作完成。

#### 2. 基础讲解

文件：`frontend/src/pages/learning/FundamentalsPage.vue`

- 保持现有文档主线、章节路径、知识结构和课堂助手逻辑。
- 不要重新设计成测试页；基础讲解完成后进入基础测试。
- 现有 `PathPicker` 和 `ChapterRail` 属于基础讲解内部导航，继续复用。

#### 3. 基础测试

建议文件：`frontend/src/pages/learning/FoundationTestPage.vue`

- 页面提供两个明确入口：`题目测试`、`费曼反讲`。
- 题目测试优先复用 `features/fundamentals/ChapterCheck.vue`、`fundamentalsApi.generateQuiz`、`getQuizSession`、`completeNode`，不要复制判题逻辑。
- 费曼反讲让用户用自己的话解释当前知识点，系统一次追问一个漏洞，并要求补充例子、反例或使用边界。
- 测试结果应记录节点掌握度、错误知识点和下一步建议；不能只保存在前端。
- 用户可随时离开；“结束本次测试”只结束会话，不自动标记节点完成。

当前实现：`FoundationTestPage.vue` 复用 `ChapterCheck.vue` 完成题目测试，并新增 `FeynmanCoach.vue` 复用 `/path/classroom/chat` 的 `feynman` 场景。反讲草稿只写入本地临时缓存，题目判分仍由后端完成。

#### 4. 进阶学习

文件：`frontend/src/pages/learning/AdvancedLearningPage.vue`

- 页面是实践任务入口，不承担长篇讲解和连续对话。
- 后端根据学习目标、身份、基础测试掌握度、薄弱点和已完成节点生成任务列表。
- 每个任务至少展示：任务情境、涉及能力、推荐原因、难度/辅助程度、预期成果、状态。
- 建议先展示一个“系统推荐”任务，再展示少量可选任务，避免堆满任务卡。
- 点击任务进入学习巩固，并携带任务、路径、节点上下文。

当前实现：后端 `GET /learning/advanced/current` 保留旧的 `task` 字段，同时返回迁移练习、案例诊断、项目实训三个 `tasks`。案例诊断是当前推荐入口，页面不在前端推算掌握度。进阶学习只展示学习状态、系统推荐和任务目录，点击后才进入学习巩固，不在此页展开阶段流程。

#### 5. 学习巩固

实现文件：`frontend/src/pages/learning/AdvancedLearningPage.vue`、`frontend/src/features/advanced/PracticeDialogue.vue`

- 这是应用实践的交互页面，不是普通聊天窗口。
- 对话阶段建议为：理解问题、寻找证据、提出假设、比较方案、验证结果、总结。
- 中央区域显示当前问题和用户回答；旁边显示“已确认事实、当前假设、待验证问题、验收标准”。
- 系统只能引导和追问，不能一开始直接给完整方案；每轮问题必须对应当前阶段。
- 用户始终可以选择：继续追问、请求提示、暂存退出、结束本次巩固、提交方案。
- `结束本次巩固` 与 `提交方案并完成` 必须是两个不同动作。

当前实现：`AdvancedLearningPage.vue` 只接收一个已选任务的上下文，使用 `PracticeDialogue.vue` 提供六个阶段、请求提示、暂存恢复和提交评价；不重复展示进阶任务目录。`advanced_practice_sessions` 保存消息、当前阶段、已完成阶段、事实/假设、提交物和评价结果，`结束本次巩固` 只把会话置为 `paused`，`提交方案并完成` 才会置为 `completed`。
- 实践追问仍通过现有课堂流式接口由学习助教 Agent 完成；任务生成 Agent 和资源审核 Agent 属于独立工作流，页面会明确区分，不能把本页描述为完整的多智能体协同展示。

### 后端与提示词任务

- 复用现有 JWT 鉴权、路径节点、资源、测验和课堂流式问答接口。
- 为基础测试和学习巩固补充明确的会话上下文 `mode`，至少区分 `foundation_test`、`feynman`、`practice`、`review`。
- 实践对话提示词必须输入：用户目标、节点掌握度、任务情境、当前阶段、已确认事实、历史对话；输出至少包含回复文本、当前阶段、下一步问题类型和是否满足结束条件。
- 追问逻辑应是苏格拉底式引导：一次只处理一个判断点，用户明确结束时立即停止追问。
- 任务生成不能只按当前节点标题套模板，要使用基础测试结果和目标模式调整任务难度、限制条件和成果形式。
- 会话状态、提交物和评价结果应由后端保存；`localStorage` 只能作为草稿缓存。
- 评分尽量使用可验证规则（选择结果、引用证据、测试指标），模型只负责解释性评价和追问。

### 建议接口契约

```text
GET  /learning/advanced/current       # 返回推荐任务和少量可选任务
POST /learning/advanced/practice/sessions                 # 创建或恢复巩固会话
PATCH /learning/advanced/practice/sessions/{id}             # 保存阶段和消息
POST /learning/advanced/practice/sessions/{id}/end          # 暂存退出
POST /learning/advanced/practice/sessions/{id}/submit       # 提交成果并触发评价
GET   /learning/advanced/practice/sessions/{id}             # 读取会话
```

如果时间不足，第一版先完成一条垂直链路：一个节点的题目测试 + 费曼反讲 + 一个企业案例巩固对话 + 一次提交评价，不要同时铺开多个领域。

### 交接时不要做的事

- 不要删除或回退别人刚更新的 `FundamentalsPage.vue`、路径接口和认证逻辑。
- 不要把基础讲解改成进阶实践，也不要把进阶实践改成再次讲课。
- 不要新增一个只展示三行链接的“学习导航”页面。
- 不要把 PPT 作为主讲内容；文档仍是基础讲解主线。
- 不要用前端假数据伪造掌握度、任务完成或评价结果。

### 验收标准

- 侧边栏能清楚看到两个绑定分组，移动端不溢出。
- 基础讲解可以进入基础测试，基础测试同时包含题目测试和费曼反讲。
- 基础测试结果能够影响进阶任务的推荐。
- 进阶学习能展示多个有差异的实践任务，并进入指定的学习巩固会话。
- 学习巩固可以连续追问，用户可随时结束，退出后能恢复上下文。
- “结束会话”和“提交完成”状态不同，概览能正确显示暂停、进行中和完成。
- 前端通过统一 API 请求并携带 JWT；完成 `npm run build`、后端语法检查和 `git diff --check`。

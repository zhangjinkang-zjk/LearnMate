# LearnMate 当前交接记录

更新时间：2026-09-04

## 当前分支与提交

- 分支：`main`
- 当前 HEAD：`5586c01f fix(frontend): proxy learning api requests`
- 主要基线：`46f39e5e refactor(frontend): remove legacy ppt workspace`
- 本地没有推送远程。远程 `main` 曾与本地分叉，未经确认不要强推。

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

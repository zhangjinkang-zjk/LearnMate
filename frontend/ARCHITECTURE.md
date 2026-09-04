# LearnMate 前端架构

前端继续使用 Vue 3 + Vite + Vue Router，图标使用 `lucide-vue-next`，样式使用普通 CSS（保留 Vite 的 Tailwind 插件能力）。应用按“应用入口、页面、业务功能、领域模型、共享能力”分层。

## 目录约定

```text
src/
├─ app/                  # 应用装配：App、main、router
├─ layouts/              # 页面布局壳：侧边主导航、顶部状态栏
├─ pages/                # 路由页面，只负责页面编排
│  ├─ home/              # 沉浸式首页
│  ├─ onboarding/        # 学习定向、能力诊断、诊断结果
│  ├─ learning/          # 学习概览、任务分析、基础讲解、进阶、工作区
│  ├─ resources/         # 资料库
│  └─ settings/          # 用户设置
├─ widgets/              # 跨页面业务区块，如学习阶段卡、系统推荐
├─ features/             # 单一业务动作及其状态，如学习定向、诊断
├─ entities/             # 稳定领域数据和状态，如 learningState
└─ shared/               # 跨业务复用：UI、配置、资源、样式、接口客户端
```

## 依赖方向

页面可以组合 `widgets`、`features`、`entities` 和 `shared`；`widgets` 可以依赖 `entities` 与 `shared`；`shared` 不依赖页面。路由只放在 `app/router`，业务页面不直接维护导航菜单。

## 学习主流程

`学习定向 → 能力诊断 → 诊断结果确认 → 学习概览 → 任务分析 → 基础讲解 → 进阶学习 → 学习工作区`

资料库和设置属于工具入口，不放入学习主线。首页和学习定向使用沉浸式布局，其余页面统一使用 `layouts/AppShell.vue`。

## 新增代码规则

- 路由页面使用 `*Page.vue` 命名，通用区块使用 `*Panel.vue`、`*Card.vue`。
- 接口客户端统一放在 `shared/api`，不要在页面中直接创建 Axios 实例。
- 学习过程状态放在 `entities` 或对应 `features`，不要通过跨组件事件传递全局数据。
- 图片、字体等静态资源按用途放在 `shared/assets`，文件名使用小写英文或稳定业务名。

# LearnMate 前端架构

前端继续使用 Vue 3 + Vite + Vue Router，图标使用 `lucide-vue-next`，样式使用普通 CSS（保留 Vite 的 Tailwind 插件能力）。应用按“应用入口、页面、业务功能、领域模型、共享能力”分层。

## 目录约定

```text
src/
├─ app/                  # 应用装配：App、main、router；罗伯特也挂在这里
├─ layouts/              # 页面布局壳：侧边主导航、顶部状态栏
├─ pages/                # 路由页面，只负责页面编排
│  ├─ home/              # 沉浸式首页
│  ├─ auth/              # 登录
│  ├─ onboarding/        # 学习定向、能力诊断、画像确认
│  ├─ learning/          # 学习概览、基础讲解、基础测试、进阶学习
│  ├─ resources/         # 资料库、知识库导入
│  ├─ profile/ planner/  # 学习画像、计划本
│  ├─ notifications/     # 通知
│  └─ settings/          # 用户设置
├─ widgets/              # 跨页面业务区块，如学习阶段卡、系统推荐
├─ features/             # 单一业务动作及其状态：advanced、assistant、agent、
│                        #   fundamentals、learnmateFlow、onboarding、resources
├─ entities/             # 稳定领域数据和状态：learning、agent
├─ shared/               # 跨业务复用：api、ui、styles、auth、config、lib
└─ utils/                # 与框架无关的纯函数（如 resourceCover）
```

## 依赖方向

页面可以组合 `widgets`、`features`、`entities` 和 `shared`；`widgets` 可以依赖 `entities` 与 `shared`；`shared` 不依赖页面。路由只放在 `app/router`，业务页面不直接维护导航菜单。

## 学习主流程

```text
学习定向 → 画像访谈 → 能力诊断 → 画像确认 → 学习概览
                                              ↓
                          基础讲解 → 基础测试 → 进阶学习（IDE + 实践教练）
```

资料库和设置属于工具入口，不放入学习主线。首页、登录、学习定向、能力诊断和画像确认使用沉浸式布局，其余页面统一使用 `layouts/AppShell.vue`。

> **2026-09-30 更正。** 这一行原来写的是「… → 学习概览 → 任务分析 → 基础讲解 → 进阶学习 → 学习工作区」，两处已经不对：
> 「任务分析」和「学习工作区」都**不是页面**了，路由表里它们都重定向（前者 → 概览，后者 → 进阶学习），「学习导航」同样重定向到概览。
> 另外流程里少了**基础测试**（`/learning/foundation-test`）和**画像访谈**（`/learnmate-chat`）—— 后者是方向与学习目标实际被问出来的地方，定向页只选身份。
> 各页面的分工见 `docs/系统设计.md`。

## 新增代码规则

- 路由页面使用 `*Page.vue` 命名，通用区块使用 `*Panel.vue`、`*Card.vue`。
- 接口客户端统一放在 `shared/api`，不要在页面中直接创建 Axios 实例。
- 学习过程状态放在 `entities` 或对应 `features`，不要通过跨组件事件传递全局数据。
- 图片、字体等静态资源按用途放在 `shared/assets`，文件名使用小写英文或稳定业务名。

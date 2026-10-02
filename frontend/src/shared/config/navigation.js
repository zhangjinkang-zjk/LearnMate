import { BookOpen, Gauge, Library, Settings, Sparkles, SquareCheck } from 'lucide-vue-next'

export const primaryNavigation = [
  { label: '学习概览', to: '/learning/overview', icon: Gauge },
]

// `step` 是**学习主线的顺序**（见 `系统设计.md` 7.3 与导航那一节）。
//
// 加它是因为这里原来把一条连续的流程摆成了三个平级目的地：侧边栏是一排纯图标，
// 顺序全靠使用者自己猜 —— "用户不知道怎么用"的第一来源就是这个。序号标出来之后，
// 顺序是**看得见的**，不依赖点进去再发现。
//
// 判据故意只有"路由 + 这三行配置"：序号是流程本身的性质，不是某个学生的学习进度，
// 所以不需要任何接口。**完成状态是另一回事**（那要读学习数据，壳子就得每次请求），
// 这次不做 —— 别把序号和进度混成一件事。
export const learningNavigationGroups = [
  {
    label: '知识学习',
    items: [
      { label: '基础学习', to: '/learning/fundamentals', icon: BookOpen, step: 1 },
      { label: '学习复盘', to: '/learning/foundation-test', icon: SquareCheck, step: 2 },
    ],
  },
  {
    label: '应用实践',
    items: [
      { label: '进阶学习', to: '/learning/advanced', icon: Sparkles, step: 3 },
    ],
  },
]

export const secondaryNavigation = [
  { label: '资料库', to: '/resources', icon: Library },
]

export const utilityNavigation = [{ label: '设置', to: '/settings', icon: Settings }]

export const allNavigation = [
  ...primaryNavigation,
  ...learningNavigationGroups.flatMap((group) => group.items),
  ...secondaryNavigation,
  ...utilityNavigation,
]

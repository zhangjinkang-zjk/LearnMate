import { BookOpen, Gauge, Library, MessageCircle, Settings, Sparkles, SquareCheck } from 'lucide-vue-next'

export const primaryNavigation = [
  { label: '学习概览', to: '/learning/overview', icon: Gauge },
]

export const learningNavigationGroups = [
  {
    label: '知识学习',
    items: [
      { label: '基础讲解', to: '/learning/fundamentals', icon: BookOpen },
      { label: '基础测试', to: '/learning/foundation-test', icon: SquareCheck },
    ],
  },
  {
    label: '应用实践',
    items: [
      { label: '进阶学习', to: '/learning/advanced', icon: Sparkles },
      { label: '学习巩固', to: '/learning/consolidation', icon: MessageCircle },
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

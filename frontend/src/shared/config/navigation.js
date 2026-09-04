import { BookOpen, Compass, FileText, Gauge, Library, Settings, Sparkles, Target } from 'lucide-vue-next'

export const primaryNavigation = [
  { label: '学习概览', to: '/learning/overview', icon: Gauge },
  { label: '任务分析', to: '/learning/task-analysis', icon: Target },
  { label: '基础讲解', to: '/learning/fundamentals', icon: BookOpen },
  { label: '进阶学习', to: '/learning/advanced', icon: Sparkles },
]

export const secondaryNavigation = [
  { label: '学习导航', to: '/learning/navigation', icon: Compass },
  { label: '学习工作区', to: '/learning/workspace', icon: FileText },
  { label: '资料库', to: '/resources', icon: Library },
]

export const utilityNavigation = [{ label: '设置', to: '/settings', icon: Settings }]

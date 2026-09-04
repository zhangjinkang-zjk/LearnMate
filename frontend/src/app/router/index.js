import { createRouter, createWebHashHistory } from 'vue-router'

import HomePage from '@/pages/home/HomePage.vue'
import DirectionSetupPage from '@/pages/onboarding/DirectionSetupPage.vue'
import DiagnosisPage from '@/pages/onboarding/DiagnosisPage.vue'
import DiagnosisResultPage from '@/pages/onboarding/DiagnosisResultPage.vue'
import OverviewPage from '@/pages/learning/OverviewPage.vue'
import FundamentalsPage from '@/pages/learning/FundamentalsPage.vue'
import AdvancedLearningPage from '@/pages/learning/AdvancedLearningPage.vue'
import NavigationPage from '@/pages/learning/NavigationPage.vue'
import WorkspacePage from '@/pages/learning/WorkspacePage.vue'
import ResourceLibraryPage from '@/pages/resources/ResourceLibraryPage.vue'
import SettingsPage from '@/pages/settings/SettingsPage.vue'
import LoginPage from '@/pages/auth/LoginPage.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: HomePage, meta: { layout: 'immersive' } },
    { path: '/login', name: 'login', component: LoginPage, meta: { layout: 'immersive' } },
    { path: '/onboarding/direction', name: 'directionSetup', component: DirectionSetupPage, meta: { layout: 'immersive', requiresAuth: true } },
    { path: '/select-identity', redirect: '/onboarding/direction' },
    { path: '/onboarding/diagnosis', name: 'diagnosis', component: DiagnosisPage, meta: { layout: 'immersive', requiresAuth: true } },
    { path: '/onboarding/diagnosis/result', name: 'diagnosisResult', component: DiagnosisResultPage, meta: { layout: 'immersive', requiresAuth: true } },
    { path: '/learning/overview', name: 'learningOverview', component: OverviewPage, meta: { requiresAuth: true } },
    { path: '/learning/task-analysis', redirect: '/learning/overview' },
    { path: '/learning/fundamentals', name: 'fundamentals', component: FundamentalsPage, meta: { requiresAuth: true } },
    { path: '/learning/advanced', name: 'advancedLearning', component: AdvancedLearningPage, meta: { requiresAuth: true } },
    { path: '/learning/navigation', name: 'learningNavigation', component: NavigationPage, meta: { requiresAuth: true } },
    { path: '/learning/workspace', name: 'learningWorkspace', component: WorkspacePage, meta: { requiresAuth: true } },
    { path: '/resources', name: 'resourceLibrary', component: ResourceLibraryPage, meta: { requiresAuth: true } },
    { path: '/settings', name: 'settings', component: SettingsPage, meta: { requiresAuth: true } },
    { path: '/:pathMatch(.*)*', redirect: '/learning/overview' },
  ],
})

router.beforeEach((to) => {
  const hasToken = Boolean(localStorage.getItem('token'))
  if (to.meta.requiresAuth && !hasToken) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.name === 'login' && hasToken) return '/learning/overview'
  return true
})

export default router

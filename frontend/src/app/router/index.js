import { createRouter, createWebHashHistory } from 'vue-router'

import HomePage from '@/pages/home/HomePage.vue'
import DirectionSetupPage from '@/pages/onboarding/DirectionSetupPage.vue'
import DiagnosisPage from '@/pages/onboarding/DiagnosisPage.vue'
import DiagnosisResultPage from '@/pages/onboarding/DiagnosisResultPage.vue'
import OverviewPage from '@/pages/learning/OverviewPage.vue'
import TaskAnalysisPage from '@/pages/learning/TaskAnalysisPage.vue'
import FundamentalsPage from '@/pages/learning/FundamentalsPage.vue'
import AdvancedLearningPage from '@/pages/learning/AdvancedLearningPage.vue'
import NavigationPage from '@/pages/learning/NavigationPage.vue'
import WorkspacePage from '@/pages/learning/WorkspacePage.vue'
import ResourceLibraryPage from '@/pages/resources/ResourceLibraryPage.vue'
import SettingsPage from '@/pages/settings/SettingsPage.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: HomePage, meta: { layout: 'immersive' } },
    { path: '/onboarding/direction', name: 'directionSetup', component: DirectionSetupPage, meta: { layout: 'immersive' } },
    { path: '/select-identity', redirect: '/onboarding/direction' },
    { path: '/onboarding/diagnosis', name: 'diagnosis', component: DiagnosisPage },
    { path: '/onboarding/diagnosis/result', name: 'diagnosisResult', component: DiagnosisResultPage },
    { path: '/learning/overview', name: 'learningOverview', component: OverviewPage },
    { path: '/learning/task-analysis', name: 'taskAnalysis', component: TaskAnalysisPage },
    { path: '/learning/fundamentals', name: 'fundamentals', component: FundamentalsPage },
    { path: '/learning/advanced', name: 'advancedLearning', component: AdvancedLearningPage },
    { path: '/learning/navigation', name: 'learningNavigation', component: NavigationPage },
    { path: '/learning/workspace', name: 'learningWorkspace', component: WorkspacePage },
    { path: '/resources', name: 'resourceLibrary', component: ResourceLibraryPage },
    { path: '/settings', name: 'settings', component: SettingsPage },
    { path: '/:pathMatch(.*)*', redirect: '/learning/overview' },
  ],
})

export default router

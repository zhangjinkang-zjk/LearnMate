import { clearWorkspaceStorage } from '@/shared/storage/workspaceDraftStore'

/**
 * Clear the browser-side authentication state.
 *
 * The backend uses stateless JWTs, so logout is represented by removing the
 * client token. Learning preferences and progress are intentionally kept so
 * signing back in does not discard the learner's local context.
 */
export function clearAuthSession() {
  localStorage.removeItem('token')
  localStorage.removeItem('learnmate_username')
  // These values are onboarding drafts, not an account data store. Clear them
  // on logout so the next account in this browser cannot inherit them.
  for (const key of [
    'learnmate_identity',
    'learnmate_direction',
    'learnmate_goal',
    'learnmate_onboarding_complete',
  ]) {
    localStorage.removeItem(key)
  }
  // Also onboarding drafts, but these live in sessionStorage. They used to sit in
  // the localStorage loop above, where removeItem was a no-op — so on a shared tab
  // the next account could still read the previous one's diagnosis result
  // (PortraitSummaryPage reads learnmate_diagnosis_result) and interview answers.
  for (const key of [
    'learnmate_diagnosis_result',
    'learnmate_portrait_dialogue',
    'learnmate_portrait_summary',
  ]) {
    sessionStorage.removeItem(key)
  }
  // 进阶学习的工作区草稿（IndexedDB）同理，而且更要紧 —— 里面是学生**自己的代码**。
  // 不 await：登出不该被一次数据库删除拖住，而且三个调用点全都是同步的、没有接
  // Promise 的地方。清不掉最坏是留一份草稿，而不是登不出去。
  clearWorkspaceStorage()
}

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
}

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
    'learnmate_diagnosis_result',
    // Set when the profile is confirmed, cleared when the diagnosis is answered.
    // Without this, an abandoned diagnosis would send the next account here.
    'learnmate_diagnosis_pending',
  ]) {
    localStorage.removeItem(key)
  }
}

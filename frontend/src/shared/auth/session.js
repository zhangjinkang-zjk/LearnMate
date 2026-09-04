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
}

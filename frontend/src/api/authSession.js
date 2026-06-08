let onUnauthorized = null;

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

export function clearAuthSession() {
  localStorage.removeItem("current_user_id");
  localStorage.removeItem("current_username");
  localStorage.removeItem("access_token");
  localStorage.removeItem("current_fitness_session_id");
}

export function triggerUnauthorized() {
  clearAuthSession();
  if (onUnauthorized) {
    onUnauthorized();
  }
}

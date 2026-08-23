const SYSTEM_COMMENT_MARKER = /(^|[^A-Za-z0-9_])system([^A-Za-z0-9_]|$)/i;

export interface SystemClientCandidate {
  comment?: unknown;
  is_system?: unknown;
}

/** Keep the UI behaviour aligned with the backend's Comment-based marker. */
export function isSystemClientComment(comment: unknown): boolean {
  return typeof comment === 'string' && SYSTEM_COMMENT_MARKER.test(comment);
}

export function isSystemClient(client: SystemClientCandidate): boolean {
  return client.is_system === true || isSystemClientComment(client.comment);
}

type RuntimeAuth = {
  username: string;
  password: string;
  totpCode: string;
  wsTicket: string;
};

function clearLegacyRuntimeAuth(): void {
  if (typeof window === 'undefined') return;
  window.sessionStorage.removeItem('sub_auth_runtime_v1');
}

// Credentials and short-lived WebSocket tickets stay memory-only.
clearLegacyRuntimeAuth();
let runtimeAuth: RuntimeAuth = { username: '', password: '', totpCode: '', wsTicket: '' };

export function setAuthCredentials(username: string, password: string, totpCode: string = '', wsTicket = ''): void {
  runtimeAuth = { username, password, totpCode, wsTicket };
}

export function setWsTicket(wsTicket: string): void {
  runtimeAuth = { ...runtimeAuth, wsTicket };
}

export function clearAuthCredentials(): void {
  runtimeAuth = { username: '', password: '', totpCode: '', wsTicket: '' };
  clearLegacyRuntimeAuth();
}

export function getAuth(): { username: string; password: string; user: string; totpCode: string; wsTicket: string } {
  return {
    username: runtimeAuth.username,
    password: runtimeAuth.password,
    user: runtimeAuth.username,
    totpCode: runtimeAuth.totpCode,
    wsTicket: runtimeAuth.wsTicket,
  };
}

export function rememberUsername(username: string): void {
  void username;
}

export function loadRememberedUsername(): string {
  return '';
}

type RuntimeAuth = {
  username: string;
  password: string;
  totpCode: string;
};

const USERNAME_KEY = 'sub_auth_user';
const LEGACY_KEY = 'sub_auth';

let runtimeAuth: RuntimeAuth = { username: '', password: '', totpCode: '' };

export function setAuthCredentials(username: string, password: string, totpCode: string = ''): void {
  runtimeAuth = { username, password, totpCode };
}

export function clearAuthCredentials(): void {
  runtimeAuth = { username: '', password: '', totpCode: '' };
}

export function getAuth(): { username: string; password: string; user: string; totpCode: string } {
  return {
    username: runtimeAuth.username,
    password: runtimeAuth.password,
    user: runtimeAuth.username,
    totpCode: runtimeAuth.totpCode,
  };
}

export function rememberUsername(username: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(USERNAME_KEY, username);
}

export function loadRememberedUsername(): string {
  if (typeof window === 'undefined') return '';

  const direct = localStorage.getItem(USERNAME_KEY);
  if (direct) return direct;

  // Migrate old auth payload and remove persisted password.
  const legacy = localStorage.getItem(LEGACY_KEY);
  if (!legacy) return '';
  try {
    const parsed = JSON.parse(legacy);
    const user = typeof parsed?.user === 'string' ? parsed.user : '';
    if (user) {
      localStorage.setItem(USERNAME_KEY, user);
    }
  } catch {
    // Ignore invalid legacy payload.
  }
  localStorage.removeItem(LEGACY_KEY);
  return localStorage.getItem(USERNAME_KEY) || '';
}

type RuntimeAuth = {
  username: string;
  password: string;
  totpCode: string;
};

const USERNAME_KEY = 'sub_auth_user';
const LEGACY_KEY = 'sub_auth';
const SESSION_AUTH_KEY = 'sub_auth_runtime_v1';

function loadRuntimeAuth(): RuntimeAuth {
  if (typeof window === 'undefined') return { username: '', password: '', totpCode: '' };
  const raw = sessionStorage.getItem(SESSION_AUTH_KEY);
  if (!raw) return { username: '', password: '', totpCode: '' };
  try {
    const parsed = JSON.parse(raw);
    return {
      username: typeof parsed?.username === 'string' ? parsed.username : '',
      password: typeof parsed?.password === 'string' ? parsed.password : '',
      totpCode: typeof parsed?.totpCode === 'string' ? parsed.totpCode : '',
    };
  } catch {
    sessionStorage.removeItem(SESSION_AUTH_KEY);
    return { username: '', password: '', totpCode: '' };
  }
}

function persistRuntimeAuth(auth: RuntimeAuth): void {
  if (typeof window === 'undefined') return;
  if (!auth.username || !auth.password) {
    sessionStorage.removeItem(SESSION_AUTH_KEY);
    return;
  }
  sessionStorage.setItem(SESSION_AUTH_KEY, JSON.stringify(auth));
}

let runtimeAuth: RuntimeAuth = loadRuntimeAuth();

export function setAuthCredentials(username: string, password: string, totpCode: string = ''): void {
  runtimeAuth = { username, password, totpCode };
  persistRuntimeAuth(runtimeAuth);
}

export function clearAuthCredentials(): void {
  runtimeAuth = { username: '', password: '', totpCode: '' };
  persistRuntimeAuth(runtimeAuth);
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

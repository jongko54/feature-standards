export interface AuthSession {
  user: { id: string; email: string };
  csrfToken: string;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, public retryAfter = 0) {
    super(code);
    this.name = 'ApiError';
  }
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

function isSession(value: unknown): value is AuthSession {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<AuthSession>;
  return Boolean(candidate.user && typeof candidate.user.id === 'string'
    && typeof candidate.user.email === 'string' && typeof candidate.csrfToken === 'string'
    && candidate.csrfToken.length > 0);
}

export function createAuthApi(fetcher: Fetch = fetch) {
  async function request(path: string, options: RequestInit = {}, expectedStatus?: number): Promise<unknown> {
    const response = await fetcher(path, { ...options, credentials: 'same-origin', cache: 'no-store' });
    let body: unknown;
    if (response.status !== 204) {
      try { body = await response.json(); }
      catch { throw new ApiError(response.status, 'INVALID_RESPONSE'); }
    }
    if (!response.ok) {
      const code = body && typeof body === 'object' && 'error' in body
        && body.error && typeof body.error === 'object' && 'code' in body.error
        && typeof body.error.code === 'string' ? body.error.code : 'REQUEST_FAILED';
      const seconds = Number(response.headers.get('Retry-After'));
      const retryAfter = Number.isSafeInteger(seconds) && seconds > 0 ? Math.min(seconds, 86400) : 0;
      throw new ApiError(response.status, code, retryAfter);
    }
    if (expectedStatus !== undefined && response.status !== expectedStatus) throw new ApiError(response.status, 'INVALID_RESPONSE');
    return body;
  }

  async function sessionRequest(path: string, options?: RequestInit): Promise<AuthSession> {
    const result = await request(path, options);
    if (!isSession(result)) throw new ApiError(200, 'INVALID_RESPONSE');
    return result;
  }

  return {
    async me(signal?: AbortSignal): Promise<AuthSession | null> {
      try { return await sessionRequest('/auth/me', { signal }); }
      catch (error) {
        if (error instanceof ApiError && error.status === 401 && error.code === 'UNAUTHENTICATED') return null;
        throw error;
      }
    },
    async login(email: string, password: string): Promise<AuthSession> {
      return sessionRequest('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
    },
    async logout(csrfToken: string): Promise<void> {
      await request('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrfToken } });
    },
    async register(email: string, password: string): Promise<void> {
      await account('/auth/register', { email, password }, true);
    },
    async requestVerification(email: string): Promise<void> {
      await account('/auth/email-verification/request', { email }, true);
    },
    async confirmVerification(token: string): Promise<void> {
      await account('/auth/email-verification/confirm', { token });
    },
    async requestPasswordReset(email: string): Promise<void> {
      await account('/auth/password-reset/request', { email }, true);
    },
    async confirmPasswordReset(token: string, password: string): Promise<void> {
      await account('/auth/password-reset/confirm', { token, password });
    },
  };

  async function account(path: string, body: object, accepted = false): Promise<void> {
    const result = await request(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }, accepted ? 202 : 204);
    if (accepted && (!result || typeof result !== 'object'
      || !('status' in result) || result.status !== 'accepted')) throw new ApiError(202, 'INVALID_RESPONSE');
    if (!accepted && result !== undefined) throw new ApiError(204, 'INVALID_RESPONSE');
  }
}

export const authApi = createAuthApi();

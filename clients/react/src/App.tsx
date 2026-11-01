import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, authApi, type AuthSession } from './api';

type Action = 'restore' | 'login' | 'logout' | 'refresh' | null;

function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return '서버에 연결할 수 없습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.';
  if (error.code === 'INVALID_CREDENTIALS') return '이메일 또는 비밀번호를 확인해 주세요.';
  if (error.code === 'RATE_LIMITED') return '로그인 시도가 많습니다. 잠시 후 다시 시도해 주세요.';
  if (error.code === 'CSRF_INVALID') return '세션 확인 정보가 일치하지 않습니다. 세션 상태를 확인한 뒤 다시 로그아웃해 주세요.';
  if (error.code === 'ORIGIN_DENIED') return '이 주소에서는 인증 요청을 허용하지 않습니다. 서버의 허용 주소 설정을 확인해 주세요.';
  if (error.code === 'INVALID_RESPONSE') return '서버 응답을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.';
  return '요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.';
}

export function App() {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [action, setAction] = useState<Action>('restore');
  const [email, setEmail] = useState('demo@example.com');
  const [password, setPassword] = useState('');
  const [notice, setNotice] = useState('저장된 세션을 확인하고 있습니다.');
  const [error, setError] = useState('');
  const [retryUntil, setRetryUntil] = useState(0);
  const [now, setNow] = useState(Date.now());
  const retrySeconds = Math.max(0, Math.ceil((retryUntil - now) / 1000));
  const busy = action !== null;

  useEffect(() => {
    const controller = new AbortController();
    void authApi.me(controller.signal).then((restored) => {
      if (controller.signal.aborted) return;
      setSession(restored);
      setNotice(restored ? '로그인 상태를 복원했습니다.' : '로그인하면 현재 세션을 확인할 수 있습니다.');
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) { setError(errorMessage(cause)); setNotice('세션 상태를 확인하지 못했습니다.'); }
    }).finally(() => { if (!controller.signal.aborted) setAction(null); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!retryUntil) return;
    const interval = window.setInterval(() => {
      const current = Date.now();
      setNow(current);
      if (current >= retryUntil) setRetryUntil(0);
    }, 500);
    return () => window.clearInterval(interval);
  }, [retryUntil]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || retrySeconds) return;
    setAction('login'); setError('');
    try {
      const loggedIn = await authApi.login(email, password);
      setSession(loggedIn); setPassword(''); setRetryUntil(0);
      setNotice('로그인했습니다. 새로고침해도 세션이 유지됩니다.');
    } catch (cause) {
      setError(errorMessage(cause));
      if (cause instanceof ApiError && cause.status === 429) {
        const start = Date.now(); setNow(start); setRetryUntil(start + (cause.retryAfter || 1) * 1000);
      }
    } finally { setAction(null); }
  }

  async function refresh() {
    if (busy) return;
    setAction('refresh'); setError('');
    try {
      const current = await authApi.me();
      const wasSignedIn = session !== null;
      setSession(current);
      setNotice(current ? '세션이 유효합니다.' : wasSignedIn ? '세션이 만료되었습니다. 다시 로그인해 주세요.' : '현재 로그인된 세션이 없습니다.');
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setAction(null); }
  }

  async function logout() {
    if (busy || !session) return;
    setAction('logout'); setError('');
    try {
      await authApi.logout(session.csrfToken);
      setSession(null); setNotice('로그아웃했습니다. 서버 세션이 종료되었습니다.');
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setAction(null); }
  }

  return (
    <main className="shell">
      <header className="page-header">
        <a className="wordmark" href="/" aria-label="Feature Standards 홈"><span className="wordmark-icon" aria-hidden="true">F</span> Feature Standards</a>
        <span className="version">browser-session-v1</span>
      </header>
      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">AUTH / REFERENCE CLIENT</p>
        <h1 id="page-title">하나의 규격,<br />같은 로그인 경험.</h1>
        <p className="description">로그인부터 세션 확인, 로그아웃까지.<br className="desktop-break" /> 같은 화면으로 서버 구현의 동작을 확인합니다.</p>
      </section>
      <section className="auth-card" aria-labelledby="auth-title" aria-busy={busy}>
        <div className="card-heading">
          <div><p className="eyebrow">YOUR SESSION</p><h2 id="auth-title">{session ? '로그인되었습니다' : '로그인'}</h2></div>
          <span className={`state-badge ${session ? 'active' : ''}`}><span aria-hidden="true" />{action === 'restore' ? '확인 중' : session ? '인증됨' : '비로그인'}</span>
        </div>
        {session ? (
          <div className="session-content">
            <div className="avatar" aria-hidden="true">{session.user.email.slice(0, 1).toUpperCase()}</div>
            <p className="session-email" data-testid="session-email">{session.user.email}</p>
            <p className="muted">서버가 현재 세션을 확인했습니다.</p>
            <dl className="session-details"><div><dt>사용자 ID</dt><dd>{session.user.id}</dd></div><div><dt>인증 방식</dt><dd>서버 세션 · HttpOnly 쿠키</dd></div></dl>
            <button className="primary" type="button" onClick={() => void logout()} disabled={busy}>{action === 'logout' ? '로그아웃 중…' : '로그아웃'}</button>
          </div>
        ) : (
          <form onSubmit={(event) => void login(event)}>
            <label htmlFor="email">이메일</label>
            <input id="email" name="email" type="text" inputMode="email" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} disabled={busy} />
            <label htmlFor="password">비밀번호</label>
            <input id="password" name="password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} placeholder="비밀번호를 입력해 주세요" />
            <button className="primary" type="submit" disabled={busy || retrySeconds > 0}>{action === 'login' ? '로그인 중…' : retrySeconds > 0 ? `${retrySeconds}초 후 다시 시도` : '로그인'}</button>
            <details className="demo-account"><summary>로컬 데모 계정 보기</summary><p>이메일 <code>demo@example.com</code></p><p>비밀번호 <code>correct-horse-battery-staple</code></p><p>서버의 데모 모드가 켜져 있을 때 사용할 수 있습니다.</p></details>
          </form>
        )}
        <div className="feedback">
          <p className="notice" role="status" aria-live="polite">{notice}</p>
          {error && <p className="error" role="alert">{error}</p>}
        </div>
        <button className="text-button" type="button" onClick={() => void refresh()} disabled={busy}>{action === 'refresh' ? '세션 확인 중…' : '세션 상태 확인'}<span aria-hidden="true"> ↗</span></button>
      </section>
      <footer className="footer"><span className="footer-dot" aria-hidden="true" />토큰은 브라우저 저장소에 저장하지 않습니다.<span className="footer-divider">·</span><span>실험적 참조 구현</span></footer>
    </main>
  );
}

import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, authApi } from './api';

export const accountsEnabled = import.meta.env.VITE_AUTH_ACCOUNT_LIFECYCLE === 'true';
export const accountPaths = ['/register', '/verify-email', '/forgot-password', '/reset-password'];

function takeToken(): string {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get('token') ?? '';
  return /^[A-Za-z0-9_-]{43}$/.test(token) ? token : '';
}

export function AccountPage() {
  const path = window.location.pathname;
  const verify = path === '/verify-email';
  const reset = path === '/reset-password';
  const register = path === '/register';
  const [token, setToken] = useState(takeToken);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [finished, setFinished] = useState(false);
  const [resend, setResend] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    window.history.replaceState(null, '', window.location.pathname);
    const receiveLink = () => {
      setToken(takeToken()); setFinished(false); setResend(false); setError(''); setNotice('');
      window.history.replaceState(null, '', window.location.pathname);
    };
    window.addEventListener('hashchange', receiveLink);
    return () => window.removeEventListener('hashchange', receiveLink);
  }, []);
  const title = verify ? '이메일 확인' : reset ? '새 비밀번호 설정' : register ? '회원가입' : '비밀번호 재설정 요청';
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try {
      if (verify && !resend) await authApi.confirmVerification(token);
      else if (verify) await authApi.requestVerification(email);
      else if (reset) await authApi.confirmPasswordReset(token, password);
      else if (register) await authApi.register(email, password);
      else await authApi.requestPasswordReset(email);
      setPassword(''); setToken(''); setFinished(true);
      setNotice(verify && !resend ? '이메일을 확인했습니다. 로그인해 주세요.'
        : reset ? '비밀번호를 변경하고 기존 세션을 종료했습니다. 다시 로그인해 주세요.'
          : '요청을 접수했습니다. 해당 계정에서 진행할 수 있는 경우 안내 메일이 전송됩니다.');
    } catch (cause) {
      setError(cause instanceof ApiError && cause.code === 'INVALID_TOKEN'
        ? '링크가 유효하지 않거나 만료되었습니다. 새 안내 메일을 요청해 주세요.'
        : cause instanceof ApiError && cause.code === 'RATE_LIMITED'
          ? '요청이 많습니다. 잠시 후 다시 시도해 주세요.'
          : cause instanceof ApiError && cause.code === 'INVALID_REQUEST'
            ? '이메일과 비밀번호 형식을 확인해 주세요. 비밀번호는 15자 이상이어야 합니다.'
            : '요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    } finally { setBusy(false); }
  }
  return <main className="shell">
    <header className="page-header"><a className="wordmark" href="/">Feature Standards</a></header>
    <section className="intro"><p className="eyebrow">YOUR ACCOUNT</p><h1>{title}</h1>
      <p className="description">안내 메일의 링크로 계정 소유를 확인합니다.<br />확인 후 로그인해 주세요.</p></section>
    <section className="auth-card" aria-busy={busy}>
      <h2>{title}</h2>
      {!finished && <form onSubmit={event => void submit(event)}>
        {(!verify && !reset || resend) && <><label htmlFor="account-email">이메일</label>
          <input id="account-email" type="text" inputMode="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /></>}
        {(register || reset) && <><label htmlFor="account-password">{reset ? '새 비밀번호' : '비밀번호'}</label>
          <input id="account-password" type="password" autoComplete="new-password" required value={password} onChange={event => setPassword(event.target.value)} />
          <p className="muted">15자 이상으로 입력해 주세요.</p></>}
        {(verify || reset) && !resend && !token && <p role="alert" className="error">유효한 메일 링크로 접속해 주세요.</p>}
        <button className="primary" disabled={busy || ((verify || reset) && !resend && !token)}>
          {verify ? resend ? '확인 메일 다시 요청' : '이메일 확인' : reset ? '비밀번호 변경' : register ? '가입 요청' : '재설정 메일 요청'}
        </button>
      </form>}
      {notice && <p role="status" className="notice">{notice}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {verify && !finished && !resend && <button className="text-button" onClick={() => { setResend(true); setError(''); }}>확인 메일 다시 요청</button>}
      <nav className="account-links"><a href="/">로그인으로 돌아가기</a><a href="/forgot-password">비밀번호 재설정</a></nav>
    </section>
  </main>;
}

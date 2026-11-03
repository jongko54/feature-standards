import { useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { authApi, type AuthSession } from '@ugauga/feature-standards-react-auth/api';
import { AccountFlow } from './AccountFlow';

const accounts = import.meta.env.VITE_AUTH_ACCOUNT_LIFECYCLE === 'true';

function App() {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [email, setEmail] = useState('demo@example.com');
  const [password, setPassword] = useState('');
  const [profile, setProfile] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  async function load(current: AuthSession | null) {
    if (current) {
      const response = await fetch('/api/profile', { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw new Error('프로필을 불러오지 못했습니다.');
      const data = await response.json();
      setProfile(`${data.user.id} / ${data.user.email}`);
    } else setProfile('');
    setSession(current);
  }
  useEffect(() => { void authApi.me().then(load).catch(() => setError('세션을 확인하지 못했습니다.')).finally(() => setBusy(false)); }, []);
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { await load(await authApi.login(email, password)); setPassword(''); }
    catch { setError('로그인하지 못했습니다.'); }
    finally { setBusy(false); }
  }
  async function logout() {
    if (!session) return;
    setBusy(true); setError('');
    try { await authApi.logout(session.csrfToken); await load(null); }
    catch { setError('로그아웃하지 못했습니다.'); }
    finally { setBusy(false); }
  }
  return <main style={{ maxWidth: 440, margin: '48px auto', padding: 24, fontFamily: 'system-ui' }}>
    <h1>별도 프로젝트의 내 프로필</h1>
    <p>공통 인증 패키지와 API 클라이언트를 가져와 사용하는 예제입니다.</p>
    {session ? <><p data-testid="profile">{profile}</p><button disabled={busy} onClick={() => void logout()}>로그아웃</button></> :
      <form onSubmit={(event) => void login(event)}>
        <label>이메일<input aria-label="이메일" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
        <label>비밀번호<input aria-label="비밀번호" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        <button disabled={busy}>로그인</button>
      </form>}
    {error && <p role="alert">{error}</p>}
    {accounts && <p><a href="/register">Register</a> · <a href="/request-reset">Request reset</a></p>}
  </main>;
}
const action = location.pathname.slice(1);
createRoot(document.getElementById('root')!).render(accounts && (action === 'register' || action === 'verify-email' || action === 'request-reset' || action === 'reset-password') ? <AccountFlow action={action} /> : <App />);

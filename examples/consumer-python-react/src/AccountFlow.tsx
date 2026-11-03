import { useEffect, useState, type FormEvent } from 'react';
import { authApi } from '@ugauga/feature-standards-react-auth/api';

type Action = 'register' | 'verify-email' | 'request-reset' | 'reset-password';

export function AccountFlow({ action }: { action: Action }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [token, setToken] = useState(() => new URLSearchParams(location.hash.slice(1)).get('token') ?? '');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { history.replaceState(null, '', location.pathname + location.search); }, []);
  const title = { register: 'Register', 'verify-email': 'Verify email', 'request-reset': 'Request reset', 'reset-password': 'Reset password' }[action];
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      if (action === 'register') await authApi.register(email, password);
      else if (action === 'verify-email') await authApi.confirmVerification(token);
      else if (action === 'request-reset') await authApi.requestPasswordReset(email);
      else await authApi.confirmPasswordReset(token, password);
      setPassword('');
      if (action === 'verify-email' || action === 'reset-password') setToken('');
      setMessage(action === 'register' || action === 'request-reset' ? 'Request accepted. Check your email.' : 'Completed. Sign in to continue.');
    } catch { setError('The request could not be completed.'); }
    finally { setBusy(false); }
  }
  return <main style={{ maxWidth: 440, margin: '48px auto', padding: 24, fontFamily: 'system-ui' }}>
    <h1>{title}</h1>
    <form onSubmit={(event) => void submit(event)}>
      {(action === 'register' || action === 'request-reset') && <label>Email<input aria-label="Email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>}
      {(action === 'register' || action === 'reset-password') && <label>{action === 'register' ? 'Password' : 'New password'}<input aria-label={action === 'register' ? 'Password' : 'New password'} type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>}
      <button disabled={busy || ((action === 'verify-email' || action === 'reset-password') && !token)}>{title}</button>
    </form>
    {message && <p role="status">{message}</p>}
    {error && <p role="alert">{error}</p>}
    <p><a href="/">Sign in</a></p>
  </main>;
}

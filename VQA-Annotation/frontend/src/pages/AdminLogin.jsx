import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService } from '../services/authService';

export default function AdminLogin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  async function submit(event) {
    event.preventDefault();
    try {
      const user = await authService.loginAdmin(email, password);
      navigate(user.system_role === 'ADMIN' ? '/admin' : '/admin/login', { replace: true });
    } catch (loginError) {
      setError(loginError.message);
    }
  }

  return (
    <main className="auth-page"><div className="auth-decoration"><img className="auth-logo" src="/Logo-DH-Cong-Nghe-Thong-Tin-UIT-V.webp" alt="VQA Annotation logo" /><h1>VQA Annotation</h1><p>Admin workspace for annotation progress and dataset quality.</p></div><form className="auth-card" onSubmit={submit}>
        <p className="admin-eyebrow">Secure workspace</p><h1 className="auth-title">Admin Portal</h1><p className="auth-subtitle">Sign in to manage tasks, users, and annotation results.</p>
        {error && <p className="auth-error">{error}</p>}
        <label className="auth-label">Email<input className="auth-input" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
        <label className="auth-label">Password<input className="auth-input" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        <button className="auth-submit" type="submit">Sign in as admin <span>→</span></button>
      </form>
    </main>
  );
}
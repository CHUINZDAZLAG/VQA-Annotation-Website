import React from 'react';
import { GoogleLogin } from '@react-oauth/google';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService } from '../services/authService';

const roleRoutes = {
  ADMIN: '/admin',
  USER: '/annotator',
};

export default function Login() {
  const navigate = useNavigate();
  const [checkingSession, setCheckingSession] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let isCurrent = true;

    authService.getCurrentUser()
      .then((user) => {
        if (isCurrent) navigate(roleRoutes[user.system_role] ?? '/login', { replace: true });
      })
      .catch(() => {
        if (isCurrent) setCheckingSession(false);
      });

    return () => {
      isCurrent = false;
    };
  }, [navigate]);

  async function handleGoogleSuccess(credentialResponse) {
    if (!credentialResponse.credential) {
      setError('Google did not return an ID token.');
      return;
    }

    try {
      const user = await authService.loginWithGoogle(credentialResponse.credential);
      if (user.system_role === 'USER') {
        navigate('/annotator', { replace: true });
      } else {
        setError('This account is configured for the admin portal. Use a student Google account here.');
      }
    } catch (loginError) {
      setError(loginError.message);
    }
  }

  if (checkingSession) {
    return (
      <main className="auth-page"><div className="auth-card"><p className="admin-eyebrow">VQA Annotation</p><p className="auth-subtitle">Checking session...</p></div>
      </main>
    );
  }

  return (
    <main className="auth-page auth-page-user"><div className="auth-decoration"><img className="auth-logo" src="/Logo-DH-Cong-Nghe-Thong-Tin-UIT-V.webp" alt="VQA Annotation logo" /><h1>VQA Annotation</h1><p>Collaborative workspace for creating accurate, reviewable visual question answering datasets.</p></div><section className="auth-card">
        <p className="admin-eyebrow">Annotator workspace</p><h1 className="auth-title">Welcome back</h1><p className="auth-subtitle">Continue with your Google account to open assigned annotation tasks.</p>
        {error && <p className="auth-error">{error}</p>}
        <div className="auth-google">
          <GoogleLogin
            onSuccess={handleGoogleSuccess}
            onError={() => setError('Google sign-in could not be completed.')}
            text="continue_with"
            shape="rectangular"
          />
        </div>
      </section>
    </main>
  );
}

import React, { useEffect, useState } from 'react';
import { Navigate, Outlet, useNavigate } from 'react-router-dom';
import { authService } from '../services/authService';

const roleRoutes = {
  ADMIN: '/admin',
  USER: '/annotator',
};

export default function ProtectedRoute({ allowedRole, portal = 'user' }) {
  const navigate = useNavigate();
  const [state, setState] = useState({ loading: true, user: null, error: null });

  useEffect(() => {
    let isCurrent = true;

    (portal === 'admin' ? authService.getCurrentAdmin() : authService.getCurrentUser())
      .then((user) => {
        if (!isCurrent) return;
        if (user.system_role !== allowedRole) {
          navigate(roleRoutes[user.system_role] ?? '/login', { replace: true });
          return;
        }
        setState({ loading: false, user, error: null });
      })
      .catch(() => {
        if (isCurrent) setState({ loading: false, user: null, error: 'unauthenticated' });
      });

    return () => {
      isCurrent = false;
    };
  }, [allowedRole, navigate, portal]);

  if (state.loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 text-white">
        <p className="text-slate-300">Checking session...</p>
      </main>
    );
  }

  if (state.error) {
    return <Navigate to={portal === 'admin' ? '/admin/login' : '/login'} replace />;
  }

  return <Outlet context={{ user: state.user }} />;
}

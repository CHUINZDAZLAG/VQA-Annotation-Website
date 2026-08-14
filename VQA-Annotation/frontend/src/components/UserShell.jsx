import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate, useOutletContext } from 'react-router-dom';
import { authService } from '../services/authService';

export default function UserShell({ children, eyebrow, title, subtitle, actions }) {
  const { user } = useOutletContext();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [driveConnection, setDriveConnection] = useState({ connected: false, account_email: null });

  useEffect(() => {
    authService.getGoogleDriveConnection().then(setDriveConnection).catch(() => {});
  }, []);

  async function connectGoogleDrive() {
    const { authorization_url: authorizationUrl } = await authService.startGoogleDriveConnection(
      `${location.pathname}${location.search}`,
    );
    window.location.assign(authorizationUrl);
  }

  async function logout() {
    await authService.logout('user');
    navigate('/login', { replace: true });
  }

  return (
    <div className={`admin-shell user-shell ${collapsed ? 'admin-shell-collapsed' : ''}`}>
      <aside className="admin-sidebar">
        <div className="admin-brand"><img className="admin-logo" src="/Logo-DH-Cong-Nghe-Thong-Tin-UIT-V.webp" alt="VQA Annotation logo" /><div className="admin-brand-copy"><strong style={{ color: '#1769f5', fontSize: 16 }}>VQA Annotation</strong><p className="admin-muted" style={{ marginTop: 2 }}>Annotator Portal</p></div></div>
        <nav className="admin-nav">
          <Link className={`admin-nav-link ${location.pathname === '/annotator' ? 'active' : ''}`} to="/annotator"><span className="admin-nav-icon">⌂</span><span>Dashboard</span></Link>
          <Link className={`admin-nav-link ${location.pathname.startsWith('/tasks') ? 'active' : ''}`} to="/tasks"><span className="admin-nav-icon">▣</span><span>My Tasks</span></Link>
        </nav>
        <div className="admin-profile-wrap"><button className="admin-profile" onClick={() => setProfileOpen(!profileOpen)} type="button"><span className="admin-avatar">{user.name?.[0]?.toUpperCase() ?? 'U'}</span><div className="admin-profile-copy" style={{ minWidth: 0, flex: 1 }}><strong style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 11 }}>{user.name}</strong><span className="admin-eyebrow" style={{ fontSize: 10 }}>ANNOTATOR</span></div><span style={{ color: '#52617a' }}>⌄</span></button>{profileOpen && <div className="admin-profile-menu"><button onClick={connectGoogleDrive} type="button">{driveConnection.connected ? 'Reconnect Google Drive' : 'Connect Google Drive'}</button><button onClick={logout} type="button">↪ &nbsp; Logout</button></div>}</div>
      </aside>
      <div className="admin-main"><header className="admin-topbar"><button className="admin-menu-button" aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} onClick={() => setCollapsed(!collapsed)} type="button">☰</button><div className="admin-topbar-user"><span style={{ color: '#52617a', fontSize: 20 }}>♧</span><button className="admin-top-profile" onClick={() => setProfileOpen(!profileOpen)} type="button"><span style={{ borderLeft: '1px solid #e7edf6', paddingLeft: 18, color: '#14213d', fontSize: 12, fontWeight: 700 }}>{user.name}<small className="admin-eyebrow" style={{ display: 'block', marginTop: 2, fontSize: 10 }}>{driveConnection.connected ? 'DRIVE CONNECTED' : 'ANNOTATOR'}</small></span><span>⌄</span></button>{profileOpen && <div className="admin-top-profile-menu"><button onClick={connectGoogleDrive} type="button">{driveConnection.connected ? 'Reconnect Google Drive' : 'Connect Google Drive'}</button><button onClick={logout} type="button">↪ &nbsp; Logout</button></div>}</div></header><main className="admin-content"><div className="flex flex-wrap items-end justify-between gap-4"><div><p className="admin-eyebrow">{eyebrow}</p><h1 className="admin-title">{title}</h1><p className="admin-subtitle">{subtitle}</p></div>{actions}</div>{children}</main></div>
    </div>
  );
}

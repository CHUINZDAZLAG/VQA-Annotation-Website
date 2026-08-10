import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { authService } from '../services/authService';
import AdminShell from '../components/AdminShell';

export default function AdminUserList() {
  const [users, setUsers] = useState([]);
  const [error, setError] = useState('');
  const [savingId, setSavingId] = useState(null);

  async function loadUsers() {
    try {
      setUsers(await authService.listAdminUsers());
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  async function toggleStatus(user) {
    setSavingId(user.id);
    setError('');
    try {
      const updatedUser = await authService.updateAdminUserStatus(user.id, !user.is_active);
      setUsers((currentUsers) => currentUsers.map((item) => item.id === updatedUser.id ? updatedUser : item));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSavingId(null);
    }
  }

  return (
    <AdminShell eyebrow="Workspace" title="User Management" subtitle="Approve student accounts before they enter the annotator portal." actions={<Link className="admin-action admin-action-secondary" to="/admin">← &nbsp;Back to dashboard</Link>}>
        {error && <p className="mt-5 text-sm text-rose-600">{error}</p>}
        <section className="admin-grid admin-grid-four mt-6">
          <div className="admin-card"><div className="admin-card-icon">♧</div><p className="admin-card-label">Total Users</p><p className="admin-card-value">{users.length}</p></div>
          <div className="admin-card"><div className="admin-card-icon">✓</div><p className="admin-card-label">Active Users</p><p className="admin-card-value">{users.filter((user) => user.is_active).length}</p></div>
          <div className="admin-card"><div className="admin-card-icon">◷</div><p className="admin-card-label">Pending Approval</p><p className="admin-card-value">{users.filter((user) => !user.is_active).length}</p></div>
          <div className="admin-card"><div className="admin-card-icon">★</div><p className="admin-card-label">Admin Accounts</p><p className="admin-card-value">{users.filter((user) => user.system_role === 'ADMIN').length}</p></div>
        </section>
        <section className="admin-section"><div className="admin-table-wrap"><table className="admin-table"><thead>
              <tr>{['Name', 'Email', 'Role', 'Status', 'Action'].map((heading) => <th key={heading}>{heading}</th>)}</tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td><strong style={{ color: '#14213d' }}>{user.name}</strong></td><td>{user.email}</td><td>{user.system_role}</td><td><span className="admin-status">{user.is_active ? 'Active' : 'Pending approval'}</span></td><td>
                    <button className="admin-action admin-action-secondary disabled:opacity-50" disabled={savingId === user.id} onClick={() => toggleStatus(user)} type="button">
                      {user.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div></section>
    </AdminShell>
  );
}

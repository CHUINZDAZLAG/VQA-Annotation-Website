import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService } from '../services/authService';
import AdminShell from '../components/AdminShell';

const initialForm = { name: '', description: '', output_type: 'MULTIPLE_CHOICE', main_annotator_id: '', blind_annotator_id: '', reviewer_id: '' };

export default function AdminTaskCreate() {
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState(initialForm);
  const [error, setError] = useState('');

  useEffect(() => { authService.listAdminUsers().then(setUsers).catch((requestError) => setError(requestError.message)); }, []);
  const update = (field) => (event) => setForm({ ...form, [field]: event.target.value });
  async function submit(event) {
    event.preventDefault();
    if (!form.name.trim()) { setError('Task name is required.'); return; }
    try {
      const task = await authService.createAdminTask({
        ...form,
        main_annotator_id: form.main_annotator_id ? Number(form.main_annotator_id) : null,
        blind_annotator_id: form.blind_annotator_id ? Number(form.blind_annotator_id) : null,
        reviewer_id: form.reviewer_id ? Number(form.reviewer_id) : null,
      });
      navigate(`/admin/tasks/${task.id}`);
    } catch (requestError) { setError(requestError.message); }
  }
  const userOptions = users.filter((user) => user.system_role === 'USER' && user.is_active);
  return <AdminShell eyebrow="Task Management" title="Create New Task" subtitle="Set up a new annotation task and assign the review team." actions={<button className="admin-action admin-action-secondary" onClick={() => navigate('/admin/tasks')} type="button">← &nbsp;Back to tasks</button>}>
    <form className="admin-form-page" onSubmit={submit}>
      <div className="admin-form-card"><div className="admin-form-heading"><div><h2 className="admin-section-title">Task details</h2><p className="admin-muted">Define the dataset task before assigning annotators.</p></div><span className="admin-form-step">1</span></div>
        {error && <p className="auth-error">{error}</p>}
        <label className="auth-label">Task Name<input className="auth-input" value={form.name} onChange={update('name')} required /></label>
        <label className="auth-label">Description<textarea className="auth-input admin-textarea" rows="4" value={form.description} onChange={update('description')} /></label>
        <label className="auth-label">Output Type<select className="auth-input" value={form.output_type} onChange={update('output_type')}><option value="MULTIPLE_CHOICE">Multiple Choice</option><option value="SHORT_ANSWER">Short Answer</option></select></label>
      </div>
      <div className="admin-form-card"><div className="admin-form-heading"><div><h2 className="admin-section-title">Assignment team</h2><p className="admin-muted">Only active user accounts can be assigned.</p></div><span className="admin-form-step">2</span></div>
        <div className="admin-form-grid">{[['main_annotator_id', 'Main Annotator'], ['blind_annotator_id', 'Blind Annotator'], ['reviewer_id', 'Reviewer']].map(([field, label]) => <label className="auth-label" key={field}>{label}<select className="auth-input" value={form[field]} onChange={update(field)}><option value="">Select User</option>{userOptions.map((user) => <option value={user.id} key={user.id}>{user.name} ({user.email})</option>)}</select></label>)}</div>
      </div>
      <div className="admin-form-actions"><button className="admin-action admin-action-secondary" onClick={() => navigate('/admin/tasks')} type="button">Cancel</button><button className="admin-action admin-action-primary" type="submit">Create Task &nbsp;→</button></div>
    </form>
  </AdminShell>;
}

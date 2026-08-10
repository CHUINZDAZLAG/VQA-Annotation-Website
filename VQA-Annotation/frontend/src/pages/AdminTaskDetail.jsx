import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { authService } from '../services/authService';
import AdminShell from '../components/AdminShell';

const assigned = (task, type) => task.assignments.find((item) => item.task_type === type);
const decisionLabel = (value) => value === 1 ? 'ACCEPT' : value === 0 ? 'REJECT' : '-';

export default function AdminTaskDetail() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);

  async function load() {
    try {
      const [taskValue, resultValue] = await Promise.all([
        authService.getAdminTask(taskId),
        authService.getAdminResults(taskId),
      ]);
      setTask(taskValue);
      setForm(taskValue);
      setResult(resultValue);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => { load(); }, [taskId]);

  async function save(event) {
    event.preventDefault();
    try {
      const value = await authService.updateAdminTask(taskId, {
        name: form.name,
        description: form.description,
        output_type: form.output_type,
        main_annotator_id: assigned(task, 'MAIN_ANNOTATOR')?.user_id ?? null,
        blind_annotator_id: assigned(task, 'BLIND_ANNOTATOR')?.user_id ?? null,
        reviewer_id: assigned(task, 'REVIEWER')?.user_id ?? null,
      });
      setTask(value);
      setForm(value);
      setEditing(false);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function archive() {
    if (!window.confirm('Archive this task?')) return;
    try {
      const value = await authService.archiveAdminTask(taskId);
      setTask(value);
      setForm(value);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function deletePermanently() {
    if (!window.confirm(`Delete task "${task?.name}" permanently?`)) return;
    if (!window.confirm('This also deletes all annotations, assignments, and export history. Continue?')) return;
    try {
      await authService.deleteAdminTaskPermanently(taskId);
      navigate('/admin/tasks', { replace: true });
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  if (error) return <main className="admin-loading-page">{error}</main>;
  if (!task || !result) return <main className="admin-loading-page">Loading task result...</main>;

  const stats = result.statistics;
  return (
    <AdminShell eyebrow="Task Management" title={editing ? `Edit Task #${task.id}` : task.name} subtitle={editing ? 'Update task configuration and assignment details.' : `Task ID: ${task.id}`} actions={<div className="admin-detail-actions"><Link className="admin-action admin-action-secondary" to="/admin/tasks">← &nbsp;Back to tasks</Link><Link className="admin-action admin-action-secondary" to={`/admin/tasks/${task.id}/results`}>View results</Link></div>}>

        <section className="admin-form-card admin-detail-card">
          {editing ? (
            <form onSubmit={save}>
              <div className="admin-form-heading"><div><h2 className="admin-section-title">Task configuration</h2><p className="admin-muted">Make changes directly on this page, then save them.</p></div></div>
              <label className="auth-label">Task Name<input className="auth-input" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
              <label className="auth-label">Description<textarea className="auth-input admin-textarea" rows="4" value={form.description ?? ''} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
              <label className="auth-label">Output Type<select className="auth-input" value={form.output_type} onChange={(event) => setForm({ ...form, output_type: event.target.value })}>
                <option>MULTIPLE_CHOICE</option><option>SHORT_ANSWER</option>
              </select></label>
              <div className="admin-form-actions" style={{ marginTop: 24 }}><button className="admin-action admin-action-secondary" onClick={() => setEditing(false)} type="button">Cancel</button><button className="admin-action admin-action-primary" type="submit">Save changes &nbsp;✓</button></div>
            </form>
          ) : (
            <>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div><p className="admin-eyebrow">Task overview</p><h2 className="admin-section-title" style={{ marginTop: 7, fontSize: 20 }}>{task.name}</h2><p className="admin-muted" style={{ marginTop: 5 }}>Task ID: {task.id}</p></div>
                <div className="admin-detail-actions"><button className="admin-action admin-action-primary" onClick={() => setEditing(true)} type="button">Edit task</button>{task.status !== 'ARCHIVED' && <button className="admin-action admin-action-secondary" onClick={archive} type="button">Archive</button>}<button className="admin-action admin-action-secondary" style={{ color: '#c76b5e' }} onClick={deletePermanently} type="button">Delete permanently</button></div>
              </div>
              <p className="admin-subtitle" style={{ marginTop: 18 }}>{task.description || 'No description.'}</p>
              <dl className="admin-detail-meta">
                <div><dt>Output Type</dt><dd>{task.output_type}</dd></div>
                <div><dt className="text-slate-400">Status</dt><dd>{task.status}</dd></div>
                <div><dt className="text-slate-400">Main Annotator</dt><dd>{assigned(task, 'MAIN_ANNOTATOR')?.user_name || 'Unassigned'}</dd></div>
                <div><dt className="text-slate-400">Blind Annotator</dt><dd>{assigned(task, 'BLIND_ANNOTATOR')?.user_name || 'Unassigned'}</dd></div>
                <div><dt className="text-slate-400">Reviewer</dt><dd>{assigned(task, 'REVIEWER')?.user_name || 'Unassigned'}</dd></div>
                <div><dt className="text-slate-400">Drive Folder</dt><dd>{task.drive_folder_id || 'Not configured'}</dd></div>
                <div><dt className="text-slate-400">Created At</dt><dd>{new Date(task.created_at).toLocaleString()}</dd></div>
                <div><dt className="text-slate-400">Updated At</dt><dd>{new Date(task.updated_at).toLocaleString()}</dd></div>
              </dl>
            </>
          )}
        </section>

        <section className="admin-section">
          <h2 className="admin-section-title">Task Result</h2>
          <div className="admin-grid admin-grid-four mt-4">
            {[['Total dataset rows', stats.total_rows], ['Multiple Choice rows', stats.multiple_choice.total], ['Short Answer rows', stats.short_answer.total], ['Combined rows', stats.combined.total]].map(([label, value]) => <div className="admin-card" key={label}><p className="admin-card-label">{label}</p><p className="admin-card-value">{value}</p></div>)}
          </div>
          <div className="admin-grid admin-grid-five mt-3">
            {['Unanimous', 'Disagreement', 'Accept', 'Reject', "Fleiss' Kappa"].map((label, index) => <div className="admin-card" key={label}><p className="admin-card-label">{label}</p><p className="admin-card-value">{[stats.combined.unanimous_agreement, stats.combined.disagreement, stats.combined.accept, stats.combined.reject, stats.combined.fleiss_kappa ?? 'Insufficient data'][index]}</p></div>)}
          </div>
        </section>

        <section className="admin-section">
          <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="admin-section-title">Dataset</h2><span className="admin-muted">Showing {result.rows.length} stored rows</span></div>
          <div className="admin-table-wrap" style={{ marginTop: 14 }}>
            <table className="admin-table" style={{ minWidth: 1350 }}><thead><tr>{['ID', 'Type', 'Image ID', 'Slide Name', 'Categories', 'Slide Type', 'Language', 'Question', 'Answer', 'Main', 'Blind', 'Reviewer', 'Generated/System fields'].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead><tbody>{result.rows.map((row) => <tr key={row.id}><td>{row.id}</td><td>{row.output_type}</td><td>{row.image_id || row.generated_image_id || '-'}</td><td>{row.slide_name || '-'}</td><td>{row.categories ?? '-'}</td><td>{row.slide_type ?? '-'}</td><td>{row.language ?? '-'}</td><td style={{ maxWidth: 190 }}><details><summary>{row.question?.question_text || '-'}</summary><pre className="mt-2 whitespace-pre-wrap text-xs">{JSON.stringify(row.question, null, 2)}</pre></details></td><td>{row.answer || '-'}</td><td>{decisionLabel(row.main_annotator?.decision)}<br /><small>{row.main_annotator?.reject_reason || ''}</small></td><td>{decisionLabel(row.blind_annotator?.decision)}<br /><small>{row.blind_annotator?.reject_reason || ''}</small></td><td>{decisionLabel(row.reviewer?.decision)}<br /><small>{row.reviewer?.reject_reason || ''}</small></td><td className="admin-muted">task_id={row.task_id}<br />annotation_id={row.id}<br />created_by={row.created_by ?? '-'}<br />page={row.page_number ?? '-'}<br />status={row.annotation_status}<br />created={new Date(row.created_at).toLocaleString()}</td></tr>)}</tbody></table>
          </div>
        </section>
    </AdminShell>
  );
}

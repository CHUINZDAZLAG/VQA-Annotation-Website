import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { authService } from '../services/authService';
import AdminShell from '../components/AdminShell';

const assignmentName = (task, type) => task.assignments.find((item) => item.task_type === type)?.user_name ?? 'Unassigned';

export default function AdminTaskList() {
  const [tasks, setTasks] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    authService.listAdminTasks().then(setTasks).catch((requestError) => setError(requestError.message));
  }, []);

  async function deletePermanently(task) {
    if (!window.confirm(`Delete task "${task.name}" permanently?`)) return;
    if (!window.confirm('This also deletes all annotations, assignments, and export history. Continue?')) return;
    try {
      await authService.deleteAdminTaskPermanently(task.id);
      setTasks((currentTasks) => currentTasks.filter((item) => item.id !== task.id));
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <AdminShell eyebrow="Workspace" title="Task Management" subtitle="Manage all annotation tasks across the system" actions={<Link className="admin-action admin-action-primary" to="/admin/tasks/create">＋ &nbsp;Create Task</Link>}>
        {error && <p className="mt-5 text-sm text-rose-600">{error}</p>}
        <section className="admin-grid admin-grid-five mt-6">
          {['Total Tasks', 'Draft', 'Waiting for Document', 'In Progress', 'Completed'].map((label, index) => <div className="admin-card" key={label}><div className="admin-card-icon">{['▣', '▤', '⇧', '⟳', '✓'][index]}</div><p className="admin-card-label">{label}</p><p className="admin-card-value">{index === 0 ? tasks.length : tasks.filter((task) => task.status === ['DRAFT', 'DRAFT', 'WAITING_FOR_DOCUMENT', 'IN_PROGRESS', 'COMPLETED'][index]).length}</p></div>)}
        </section>
        <section className="admin-section"><div className="admin-table-wrap">
          <table className="admin-table"><thead><tr>{['ID', 'Task Name', 'Description', 'Output Type', 'Main Annotator', 'Blind Annotator', 'Reviewer', 'Status', 'Drive Folder', 'Rows', 'Approved', 'Rejected', 'Kappa', 'Results', 'Actions', 'Created At', 'Updated At'].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
            <tbody>{tasks.map((task) => <tr key={task.id}>
              <td>{task.id}</td><td><Link to={`/admin/tasks/${task.id}`}>{task.name}</Link></td><td style={{ maxWidth: 220 }}>{task.description || '-'}</td><td>{task.output_type}</td><td>{assignmentName(task, 'MAIN_ANNOTATOR')}</td><td>{assignmentName(task, 'BLIND_ANNOTATOR')}</td><td>{assignmentName(task, 'REVIEWER')}</td><td><span className="admin-status">{task.status}</span></td><td>{task.drive_folder_id || '-'}</td><td>{task.result_count}</td><td style={{ color: '#159570', fontWeight: 700 }}>{task.approved_count}</td><td style={{ color: '#d58b20', fontWeight: 700 }}>{task.rejected_count}</td><td>{task.result_fleiss_kappa ?? 'Insufficient data'}</td><td><Link to={`/admin/tasks/${task.id}/results`}>View</Link></td><td><button className="admin-text-danger" onClick={() => deletePermanently(task)} type="button">Delete permanently</button></td><td>{new Date(task.created_at).toLocaleString()}</td><td>{new Date(task.updated_at).toLocaleString()}</td>
            </tr>)}</tbody>
          </table>
        </div></section>
    </AdminShell>
  );
}

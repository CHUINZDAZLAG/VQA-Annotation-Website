import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { authService } from '../services/authService';
import UserShell from '../components/UserShell';

export default function UserTaskDetail() {
  const { taskId } = useParams(); const [task, setTask] = useState(null); const [error, setError] = useState('');
  useEffect(() => { authService.getTask(taskId).then(setTask).catch((requestError) => setError(requestError.message)); }, [taskId]);
  if (error) return <main className="admin-loading-page">{error}</main>;
  if (!task) return <main className="admin-loading-page">Loading...</main>;
  return <UserShell eyebrow="My Tasks" title={task.name} subtitle={`Task #${task.id} details and annotation workspace.`} actions={<Link className="admin-action admin-action-secondary" to="/tasks">← &nbsp;Back to tasks</Link>}><section className="admin-form-card admin-detail-card"><p className="admin-subtitle">{task.description || 'No description.'}</p><dl className="admin-detail-meta"><div><dt>Output Type</dt><dd>{task.output_type}</dd></div><div><dt>Assignment</dt><dd>{task.assignments.join(', ')}</dd></div><div><dt>Status</dt><dd><span className="admin-status">{task.status}</span></dd></div><div><dt>Google Drive Link</dt><dd>{(task.drive_link || task.drive_folder_url) ? <a href={task.drive_link || task.drive_folder_url} target="_blank" rel="noreferrer">Open Drive link</a> : 'Not provided'}</dd></div></dl><div className="user-workspace-placeholder">Document Workspace <span>Open the Main Annotator workspace to upload or replace the PDF.</span></div><div className="admin-detail-actions"><Link className="admin-action admin-action-primary" to={`/tasks/${task.id}/annotate`}>Annotation Workspace &nbsp;→</Link><Link className="admin-action admin-action-secondary" to={`/tasks/${task.id}/review`}>Review Workspace</Link></div></section></UserShell>;
}

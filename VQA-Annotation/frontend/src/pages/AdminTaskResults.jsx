import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { authService } from '../services/authService';
import AdminShell from '../components/AdminShell';

const decisionLabel = (value) => value === 1 ? 'ACCEPT' : value === 0 ? 'REJECT' : '-';
const assigned = (task, type) => task?.assignments.find((item) => item.task_type === type)?.user_name ?? 'Unassigned';

function DecisionCell({ value }) {
  return <span className={value === 1 ? 'text-emerald-300' : value === 0 ? 'text-amber-300' : 'text-slate-500'}>{decisionLabel(value)}</span>;
}

export default function AdminTaskResults() {
  const { taskId } = useParams();
  const [task, setTask] = useState(null);
  const [result, setResult] = useState(null);
  const [exports, setExports] = useState([]);
  const [filters, setFilters] = useState({ output_type: '', categories: '', slide_type: '', language: '', search: '', annotation_status: '', main_annotator_decision: '', blind_annotator_decision: '', reviewer_decision: '' });
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [driveFolderId, setDriveFolderId] = useState('');

  async function load() {
    try {
      setError('');
      const [taskValue, value, exportHistory] = await Promise.all([authService.getAdminTask(taskId), authService.getAdminResults(taskId, filters), authService.listTaskExports(taskId)]);
      setTask(taskValue);
      setResult(value);
      setExports(exportHistory);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => { load(); }, [taskId, filters.output_type, filters.categories, filters.slide_type, filters.language, filters.search, filters.annotation_status, filters.main_annotator_decision, filters.blind_annotator_decision, filters.reviewer_decision]);

  function changeFilter(event) {
    setFilters({ ...filters, [event.target.name]: event.target.value });
  }

  async function exportDataset(format) {
    try {
      const value = await authService.exportTask(taskId, format);
      setMessage(`Exported ${value.file_name}${value.drive_file_id ? ' to Google Drive.' : '.'}`);
      await load();
    } catch (requestError) { setError(requestError.message); }
  }

  async function configureDrive(event) {
    event.preventDefault();
    try {
      await authService.setTaskDriveFolder(taskId, driveFolderId);
      setMessage('Google Drive folder saved.');
    } catch (requestError) { setError(requestError.message); }
  }

  if (error && !result) return <main className="admin-loading-page">{error}</main>;
  const stats = result?.statistics;
  return (
    <AdminShell eyebrow="Task Management / Results" title={task?.name || `Task Result #${taskId}`} subtitle="Inspect stored user-entered and system-generated dataset fields." actions={<div className="admin-detail-actions"><Link className="admin-action admin-action-secondary" to={`/admin/tasks/${taskId}`}>← &nbsp;Back to task</Link><button className="admin-action admin-action-primary" onClick={() => exportDataset('JSON')} type="button">Export JSON</button><button className="admin-action admin-action-secondary" onClick={() => exportDataset('CSV')} type="button">Export CSV</button></div>}>
      <div className="admin-results">
        {error && <p className="mt-4 text-amber-300">{error}</p>}
        {message && <p className="mt-4 text-emerald-300">{message}</p>}
        <section className="mt-8 border border-slate-700 bg-slate-900 p-5">
          <h2 className="text-xl font-semibold">Task Information</h2>
          <p className="mt-2 text-slate-300">{task?.description || 'No description.'}</p>
          <dl className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div><dt className="text-xs text-slate-400">Task ID</dt><dd>{task?.id ?? taskId}</dd></div>
            <div><dt className="text-xs text-slate-400">Output Type</dt><dd>{task?.output_type || '-'}</dd></div>
            <div><dt className="text-xs text-slate-400">Status</dt><dd>{task?.status || '-'}</dd></div>
            <div><dt className="text-xs text-slate-400">Drive Folder ID</dt><dd>{task?.drive_folder_id || 'Not configured'}</dd></div>
            <div><dt className="text-xs text-slate-400">Main Annotator</dt><dd>{assigned(task, 'MAIN_ANNOTATOR')}</dd></div>
            <div><dt className="text-xs text-slate-400">Blind Annotator</dt><dd>{assigned(task, 'BLIND_ANNOTATOR')}</dd></div>
            <div><dt className="text-xs text-slate-400">Reviewer</dt><dd>{assigned(task, 'REVIEWER')}</dd></div>
            <div><dt className="text-xs text-slate-400">Created At</dt><dd>{task?.created_at ? new Date(task.created_at).toLocaleString() : '-'}</dd></div>
            <div><dt className="text-xs text-slate-400">Updated At</dt><dd>{task?.updated_at ? new Date(task.updated_at).toLocaleString() : '-'}</dd></div>
          </dl>
        </section>
        <section className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[['Total Rows', stats?.total_rows ?? 0], ['Multiple Choice', stats?.multiple_choice.total ?? 0], ['Short Answer', stats?.short_answer.total ?? 0], ['Fleiss Kappa', stats?.combined.fleiss_kappa ?? 'Insufficient data']].map(([label, value]) => <div className="border border-slate-700 bg-slate-900 p-4" key={label}><p className="text-xs text-slate-400">{label}</p><p className="mt-2 text-2xl">{value}</p></div>)}
        </section>
        <section className="mt-6 grid gap-3 border border-slate-700 bg-slate-900 p-4 sm:grid-cols-3">
          <p>Unanimous: <strong>{stats?.combined.unanimous_agreement ?? 0}</strong></p><p>Disagreement: <strong>{stats?.combined.disagreement ?? 0}</strong></p><p>Complete annotations: <strong>{stats?.combined.total_annotations ?? 0}</strong></p>
        </section>
        <section className="mt-6 flex flex-wrap gap-2 border border-slate-700 bg-slate-900 p-4">
          <select className="bg-slate-800 p-2" name="output_type" value={filters.output_type} onChange={changeFilter}><option value="">All output types</option><option value="MULTIPLE_CHOICE">Multiple Choice</option><option value="SHORT_ANSWER">Short Answer</option></select>
          <input className="w-28 bg-slate-800 p-2" name="categories" placeholder="Categories" value={filters.categories} onChange={changeFilter} /><input className="w-28 bg-slate-800 p-2" name="slide_type" placeholder="Slide type" value={filters.slide_type} onChange={changeFilter} /><input className="w-28 bg-slate-800 p-2" name="language" placeholder="Language" value={filters.language} onChange={changeFilter} />
          <select className="bg-slate-800 p-2" name="annotation_status" value={filters.annotation_status} onChange={changeFilter}><option value="">All statuses</option><option value="SUBMITTED">Submitted</option><option value="REVIEWED">Reviewed</option></select>
          {['main_annotator_decision', 'blind_annotator_decision', 'reviewer_decision'].map((name) => <select className="bg-slate-800 p-2" key={name} name={name} value={filters[name]} onChange={changeFilter}><option value="">{name.replaceAll('_', ' ')}</option><option value="1">ACCEPT</option><option value="0">REJECT</option></select>)}
          <input className="min-w-64 flex-1 bg-slate-800 p-2" name="search" placeholder="Search image ID or slide name" value={filters.search} onChange={changeFilter} />
        </section>
        <section className="mt-6 overflow-x-auto border border-slate-700">
          <table className="min-w-[1450px] text-left text-sm"><thead className="bg-slate-800 text-slate-300"><tr>{['ID', 'Type', 'Image ID', 'Slide Name', 'Category', 'Slide Type', 'Language', 'Question', 'Answer', 'Main', 'Blind', 'Reviewer', 'System metadata'].map((heading) => <th className="px-3 py-3" key={heading}>{heading}</th>)}</tr></thead><tbody>{(result?.rows ?? []).map((row) => <tr className="border-t border-slate-800 align-top" key={row.id}><td className="px-3 py-3">{row.id}</td><td className="px-3 py-3">{row.output_type}</td><td className="px-3 py-3">{row.image_id || row.generated_image_id || '-'}</td><td className="px-3 py-3">{row.slide_name || '-'}</td><td className="px-3 py-3">{row.categories ?? '-'}</td><td className="px-3 py-3">{row.slide_type ?? '-'}</td><td className="px-3 py-3">{row.language ?? '-'}</td><td className="max-w-80 px-3 py-3"><details><summary>{row.question?.question_text || '-'}</summary><pre className="mt-2 whitespace-pre-wrap text-xs text-slate-400">{JSON.stringify(row.question, null, 2)}</pre></details></td><td className="px-3 py-3">{row.answer || '-'}</td><td className="px-3 py-3"><DecisionCell value={row.main_annotator?.decision} /><p className="text-xs text-slate-500">{row.main_annotator?.reject_reason || ''}</p></td><td className="px-3 py-3"><DecisionCell value={row.blind_annotator?.decision} /><p className="text-xs text-slate-500">{row.blind_annotator?.reject_reason || ''}</p></td><td className="px-3 py-3"><DecisionCell value={row.reviewer?.decision} /><p className="text-xs text-slate-500">{row.reviewer?.reject_reason || ''}</p></td><td className="px-3 py-3 text-xs text-slate-400">task={row.task_id}<br />created_by={row.created_by ?? '-'}<br />page={row.page_number ?? '-'}<br />annotation={row.annotation_status}</td></tr>)}</tbody></table>
        </section>
        <section className="mt-6 grid gap-6 lg:grid-cols-2"><form className="border border-slate-700 bg-slate-900 p-4" onSubmit={configureDrive}><h2 className="text-lg font-semibold">Google Drive folder</h2><p className="mt-2 text-sm text-slate-400">Only the backend uses service-account credentials.</p><div className="mt-4 flex gap-2"><input className="flex-1 bg-slate-800 p-2" placeholder="Drive folder ID" value={driveFolderId} onChange={(event) => setDriveFolderId(event.target.value)} /><button className="bg-white px-3 py-2 text-slate-950" type="submit">Save folder</button></div></form><div className="border border-slate-700 bg-slate-900 p-4"><h2 className="text-lg font-semibold">Export history</h2>{exports.map((item) => <p className="mt-2 text-sm" key={item.id}><button className="text-cyan-300 underline" onClick={() => authService.downloadTaskExport(taskId, item.id)} type="button">{item.file_name}</button> <span className="text-slate-400">{item.format} {new Date(item.exported_at).toLocaleString()}</span></p>)}</div></section>
      </div>
    </AdminShell>
  );
}

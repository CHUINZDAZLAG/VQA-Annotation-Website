import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { authService } from '../services/authService';
import AdminShell from '../components/AdminShell';

const initialFilters = {
  task_id: '', output_type: '', categories: '', slide_type: '', language: '', annotation_status: '',
  main_annotator_decision: '', blind_annotator_decision: '', reviewer_decision: '', search: '', page: 1, page_size: 50,
};

function Card({ icon, label, value, detail }) {
  return <div className="admin-card"><div className="admin-card-icon">{icon}</div><p className="admin-card-label">{label}</p><p className="admin-card-value">{value}</p>{detail && <p className="admin-muted">{detail}</p>}</div>;
}

function Decision({ value }) {
  return <span className={value === 1 ? 'text-emerald-300' : value === 0 ? 'text-amber-300' : 'text-slate-500'}>{value === 1 ? '1 / ACCEPT' : value === 0 ? '0 / REJECT' : '-'}</span>;
}

function AgreementPanel({ title, value }) {
  const annotators = value?.annotators ?? {};
  return (
    <section className="admin-agreement">
      <h3 className="admin-section-title">{title}</h3>
      <p className="admin-muted" style={{ marginTop: 5 }}>Records: {value?.total_records ?? 0} | Fleiss observations: {value?.observations ?? 0}</p>
      <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
        {['main', 'blind', 'reviewer'].map((role) => <div key={role}><p className="admin-agreement-role">{role === 'main' ? 'Main Annotator' : role === 'blind' ? 'Blind Annotator' : 'Reviewer'}</p><p style={{ marginTop: 7 }}>Label 0: <strong className="admin-agreement-number">{annotators[role]?.label_0 ?? 0}</strong></p><p>Label 1: <strong className="admin-agreement-number">{annotators[role]?.label_1 ?? 0}</strong></p></div>)}
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3 border-t border-slate-100 pt-3 text-xs"><p>Observed P<sub>o</sub><br /><strong>{value?.p_observed ?? '-'}</strong></p><p>Expected P<sub>e</sub><br /><strong>{value?.p_expected ?? '-'}</strong></p><p>Fleiss' Kappa<br /><strong className="text-blue-600">{value?.fleiss_kappa ?? 'Insufficient data'}</strong></p></div>
      </section>
  );
}

export default function AdminDashboard() {
  const [filters, setFilters] = useState(initialFilters);
  const [dashboard, setDashboard] = useState(null);
  const [error, setError] = useState('');

  async function load() {
    try {
      setError('');
      setDashboard(await authService.getGlobalDashboard(filters));
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => { load(); }, [filters.task_id, filters.output_type, filters.categories, filters.slide_type, filters.language, filters.annotation_status, filters.main_annotator_decision, filters.blind_annotator_decision, filters.reviewer_decision, filters.search, filters.page]);

  function changeFilter(event) {
    setFilters({ ...filters, [event.target.name]: event.target.value, page: 1 });
  }

  function changePage(offset) {
    setFilters({ ...filters, page: Math.max(1, filters.page + offset) });
  }

  const stats = dashboard?.statistics;
  const total = dashboard?.total_records ?? 0;
  const accepted = stats?.accept ?? 0;
  const rejected = stats?.reject ?? 0;
  const rate = total ? `${((accepted / (total * 3)) * 100).toFixed(1)}%` : '0%';
  const pageCount = dashboard ? Math.max(1, Math.ceil(dashboard.total_records / dashboard.page_size)) : 1;

  return (
    <AdminShell eyebrow="Overview" title="Dashboard" subtitle="Overview of annotation progress and dataset quality" actions={<div className="flex gap-2"><Link className="admin-action admin-action-primary" to="/admin/tasks">▣ &nbsp;Task Management</Link><Link className="admin-action admin-action-secondary" to="/admin/users">♧ &nbsp; User Management</Link></div>}>
        {error && <p className="mt-5 text-sm text-rose-600">{error}</p>}

        <section className="admin-grid admin-grid-five mt-6">
          <Card icon="▣" label="Total Tasks" value={dashboard?.task_count ?? 0} detail="All tasks in system" /><Card icon="▤" label="Total Annotation Records" value={total} detail="All annotation records" /><Card icon="✓" label="Approved" value={dashboard?.total_approved ?? 0} detail="Approved records" /><Card icon="×" label="Rejected" value={dashboard?.total_rejected ?? 0} detail="Rejected records" /><Card icon="Σ" label="Global Fleiss Kappa" value={stats?.fleiss_kappa ?? 'Insufficient data'} detail="Across all tasks" />
        </section>

        <section className="admin-section grid gap-3 lg:grid-cols-4">
          <Card icon="☷" label="Multiple Choice" value={dashboard?.multiple_choice_total ?? 0} detail="MC records" /><Card icon="▤" label="Short Answer" value={dashboard?.short_answer_total ?? 0} detail="SA records" /><Card icon="♡" label="Accept ratings" value={accepted} detail="Accepted ratings" /><Card icon="◔" label="Accept rate" value={rate} detail="Overall accept rate" />
        </section>

        <section className="admin-section"><h2 className="admin-section-title">Annotation Agreement</h2><p className="admin-muted" style={{ marginTop: 5 }}>Kappa uses only Main, Blind, and Reviewer binary labels from the selected database records.</p>
          <div className="admin-agreement-grid">
            <AgreementPanel title="All Data" value={dashboard?.all} />
            <AgreementPanel title="Multiple Choice" value={dashboard?.multiple_choice} />
            <AgreementPanel title="Short Answer" value={dashboard?.short_answer} />
          </div>
        </section>

        <section className="admin-section"><div className="admin-filter">
          <select className="admin-select" name="task_id" value={filters.task_id} onChange={changeFilter}><option value="">All Tasks</option>{(dashboard?.tasks ?? []).map((task) => <option value={task.id} key={task.id}>{task.name}</option>)}</select>
          <select className="admin-select" name="output_type" value={filters.output_type} onChange={changeFilter}><option value="">All Output Types</option><option value="MULTIPLE_CHOICE">Multiple Choice</option><option value="SHORT_ANSWER">Short Answer</option></select>
          <input className="admin-input" name="categories" placeholder="Category" value={filters.categories} onChange={changeFilter} /><input className="admin-input" name="slide_type" placeholder="Slide Type" value={filters.slide_type} onChange={changeFilter} /><input className="admin-input" name="language" placeholder="Language" value={filters.language} onChange={changeFilter} />
          <select className="admin-select" name="annotation_status" value={filters.annotation_status} onChange={changeFilter}><option value="">All Statuses</option><option value="SUBMITTED">Submitted</option><option value="REVIEWED">Reviewed</option></select>
          <input className="admin-input" style={{ minWidth: 230, flex: 1 }} name="search" placeholder="Search task, image, slide, question" value={filters.search} onChange={changeFilter} />
          </div>
        </section>

        <section className="admin-section"><div className="admin-table-wrap">
          <table className="admin-table"><thead><tr>{['#', 'Task', 'Task ID', 'Image ID', 'Slide Name', 'Output Type', 'Category', 'Slide Type', 'Language', 'Question', 'Answer', 'Main Label', 'Blind Label', 'Reviewer Label', 'Review Status'].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead><tbody>{(dashboard?.rows ?? []).map((row, index) => <tr key={row.id}><td>{(filters.page - 1) * filters.page_size + index + 1}</td><td><Link to={`/admin/tasks/${row.task_id}`}>{row.task_name}</Link></td><td>{row.task_id}</td><td>{row.image_id || row.generated_image_id || '-'}</td><td>{row.slide_name || '-'}</td><td>{row.output_type}</td><td>{row.categories ?? '-'}</td><td>{row.slide_type ?? '-'}</td><td>{row.language ?? '-'}</td><td style={{ maxWidth: 190 }}><details><summary>{row.question?.question_text || '-'}</summary><pre className="mt-2 whitespace-pre-wrap text-xs">{JSON.stringify(row.question, null, 2)}</pre></details></td><td>{row.answer || '-'}</td><td><Decision value={row.main_annotator?.decision} /></td><td><Decision value={row.blind_annotator?.decision} /></td><td><Decision value={row.reviewer?.decision} /></td><td><span className="admin-status">{row.annotation_status}</span></td></tr>)}</tbody></table>
        </div>
        </section>
        <div className="mt-4 flex items-center justify-between text-xs text-slate-500"><span>Showing {total ? (filters.page - 1) * filters.page_size + 1 : 0} to {Math.min(filters.page * filters.page_size, total)} of {total} records</span><div className="flex gap-2"><button className="admin-action admin-action-secondary disabled:opacity-40" disabled={filters.page <= 1} onClick={() => changePage(-1)} type="button">‹</button><span className="admin-action admin-action-primary">{filters.page}</span><button className="admin-action admin-action-secondary disabled:opacity-40" disabled={filters.page >= pageCount} onClick={() => changePage(1)} type="button">›</button></div></div>
    </AdminShell>
  );
}

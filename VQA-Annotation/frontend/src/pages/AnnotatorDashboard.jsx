import React from 'react';
import { useOutletContext } from 'react-router-dom';
import UserShell from '../components/UserShell';

export default function AnnotatorDashboard() {
  const { user } = useOutletContext();

  return <UserShell eyebrow="Overview" title="Annotator Dashboard" subtitle="Review your assigned annotation work and progress."><section className="admin-grid admin-grid-four mt-6"><div className="admin-card"><div className="admin-card-icon">▣</div><p className="admin-card-label">Assigned Tasks</p><p className="admin-card-value">-</p><p className="admin-muted">Open My Tasks to begin</p></div><div className="admin-card"><div className="admin-card-icon">✓</div><p className="admin-card-label">Completed</p><p className="admin-card-value">-</p><p className="admin-muted">Your completed work</p></div></section><section className="admin-section"><h2 className="admin-section-title">Welcome, {user.name}</h2><p className="admin-subtitle">System role: {user.system_role}. Select My Tasks from the sidebar to view your assignments.</p></section></UserShell>;
}

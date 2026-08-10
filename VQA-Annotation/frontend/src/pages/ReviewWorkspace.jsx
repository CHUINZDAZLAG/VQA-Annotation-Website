import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import UserShell from '../components/UserShell';
import { authService } from '../services/authService';

const reasons = {
  CONTENT_MISMATCH: 'Content mismatch',
  SPELLING_ERROR: 'Spelling error',
  FORMAT_ERROR: 'Format error',
  OTHER: 'Other',
};

export default function ReviewWorkspace() {
  const { taskId } = useParams();
  const [slides, setSlides] = useState([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [imageUrl, setImageUrl] = useState('');
  const [decision, setDecision] = useState(null);
  const [rejectReason, setRejectReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const selectedSlide = slides[selectedIndex];

  useEffect(() => {
    authService.getReviewSlides(taskId)
      .then(setSlides)
      .catch((requestError) => setError(requestError.message))
      .finally(() => setLoading(false));
  }, [taskId]);

  useEffect(() => {
    if (!selectedSlide) return undefined;
    let active = true;
    setDecision(selectedSlide.annotation?.reviewer_label ?? null);
    setRejectReason(selectedSlide.annotation?.reject_reason ?? '');
    authService.getReviewSlideImage(taskId, selectedSlide.id)
      .then((url) => active ? setImageUrl(url) : URL.revokeObjectURL(url))
      .catch((requestError) => active && setError(requestError.message));
    return () => { active = false; };
  }, [taskId, selectedSlide?.id]);

  async function saveReview() {
    if (decision === null) { setError('Choose Accept or Reject.'); return; }
    if (decision === 0 && !rejectReason) { setError('A reject reason is required.'); return; }
    setSaving(true); setError('');
    try {
      const saved = await authService.reviewSlide(taskId, selectedSlide.id, { decision, reject_reason: decision === 0 ? rejectReason : null });
      setSlides((current) => current.map((slide) => slide.id === selectedSlide.id ? { ...slide, annotation: saved } : slide));
      setMessage('Review decision saved.');
    } catch (requestError) { setError(requestError.message); }
    finally { setSaving(false); }
  }

  if (loading) return <main className="admin-loading-page">Loading review workspace...</main>;
  if (error && !slides.length) return <main className="admin-loading-page">{error}</main>;
  return <UserShell eyebrow="Reviewer" title="Review Workspace" subtitle={`Task #${taskId}`} actions={<Link className="admin-action admin-action-secondary" to={`/tasks/${taskId}`}>← &nbsp;Back to task</Link>}>
    {error && <p className="auth-error">{error}</p>}{message && <p className="annotation-success">{message}</p>}
    {!slides.length ? <section className="admin-section">No processed slides are available for review.</section> : <div className="annotation-layout">
      <aside className="annotation-slide-list"><h2 className="admin-section-title">Slides</h2>{slides.map((slide, index) => <button className={`annotation-slide-item ${index === selectedIndex ? 'selected' : ''}`} key={slide.id} onClick={() => setSelectedIndex(index)} type="button"><span className="annotation-slide-check">{slide.annotation?.reviewer_label === 1 ? '✓' : slide.annotation?.reviewer_label === 0 ? '×' : '○'}</span><span>Page {String(slide.page_number).padStart(2, '0')}</span><small>{slide.image_id}</small></button>)}</aside>
      <section className="annotation-preview"><img src={imageUrl} alt={selectedSlide.image_id} /><div><strong>{selectedSlide.image_id}</strong><span>Page {selectedSlide.page_number} of {slides.length}</span></div></section>
      <section className="annotation-form"><div className="annotation-form-header"><div><h2 className="admin-section-title">Review annotation</h2><p className="admin-muted">{selectedSlide.image_id}</p></div><span className="admin-status">{selectedSlide.annotation?.final_status || 'PENDING'}</span></div><p className="annotation-readonly">Question: <strong>{selectedSlide.annotation?.question?.question_text || 'Not submitted'}</strong></p><p className="annotation-readonly">Answer: <strong>{selectedSlide.annotation?.answer || 'Not submitted'}</strong></p>{selectedSlide.annotation?.similarity_score != null && <p className="annotation-readonly">Blind similarity: <strong>{selectedSlide.annotation.similarity_score}</strong></p>}<div className="admin-detail-actions" style={{ marginTop: 18 }}><button className={`admin-action ${decision === 1 ? 'admin-action-primary' : 'admin-action-secondary'}`} onClick={() => setDecision(1)} type="button">Accept</button><button className={`admin-action ${decision === 0 ? 'admin-action-primary' : 'admin-action-secondary'}`} onClick={() => setDecision(0)} type="button">Reject</button></div>{decision === 0 && <label className="auth-label">Reject reason<select className="auth-input" value={rejectReason} onChange={(event) => setRejectReason(event.target.value)}><option value="">Select a reason</option>{Object.entries(reasons).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>}<button className="admin-action admin-action-primary" style={{ marginTop: 22 }} disabled={saving} onClick={saveReview} type="button">{saving ? 'Saving...' : 'Save review decision'}</button></section>
    </div>}
  </UserShell>;
}

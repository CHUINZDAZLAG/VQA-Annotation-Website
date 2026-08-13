import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import UserShell from '../components/UserShell';
import { authService } from '../services/authService';

function blankAnnotation() {
  return { question_text: '', option_a: '', option_b: '', option_c: '', option_d: '', answer: '' };
}

export default function BlindWorkspace() {
  const { taskId } = useParams();
  const [slides, setSlides] = useState([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [form, setForm] = useState(blankAnnotation());
  const [imageUrl, setImageUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [decision, setDecision] = useState(null);
  const [rejectReason, setRejectReason] = useState('');
  const selectedSlide = slides[selectedIndex];
  const isMultipleChoice = selectedSlide?.output_type === 'MULTIPLE_CHOICE';

  useEffect(() => {
    authService.getBlindSlides(taskId).then(setSlides).catch((requestError) => setError(requestError.message)).finally(() => setLoading(false));
  }, [taskId]);

  useEffect(() => {
    if (!selectedSlide) return undefined;
    let active = true;
    setForm({ ...blankAnnotation(), ...(selectedSlide.blind_question || {}), answer: selectedSlide.blind_answer || '' });
    setDecision(selectedSlide.blind_label ?? null);
    setRejectReason(selectedSlide.reject_reason || '');
    authService.getBlindSlideImage(taskId, selectedSlide.slide_id).then((url) => active ? setImageUrl(url) : URL.revokeObjectURL(url)).catch((requestError) => active && setError(requestError.message));
    return () => { active = false; };
  }, [taskId, selectedSlide?.id, selectedSlide?.slide_id]);

  const update = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));
  async function save() {
    if (!form.question_text.trim() || !form.answer.trim()) { setError('Question and answer are required.'); return; }
    if (isMultipleChoice && ['option_a', 'option_b', 'option_c', 'option_d'].some((field) => !form[field].trim())) { setError('All multiple-choice options are required.'); return; }
    setSaving(true); setError('');
    try {
      const question = { question_text: form.question_text, option_a: form.option_a, option_b: form.option_b, option_c: form.option_c, option_d: form.option_d };
      const saved = await authService.saveBlindAnnotation(taskId, selectedSlide.id, { question, answer: form.answer });
      setSlides((current) => current.map((slide) => slide.id === selectedSlide.id ? { ...slide, blind_question: saved.blind_question, blind_answer: saved.blind_answer, similarity_score: saved.similarity_score } : slide));
      setMessage('Blind annotation saved.');
    } catch (requestError) { setError(requestError.message); }
    finally { setSaving(false); }
  }
  async function saveDecision() {
    if (decision === null) { setError('Choose Accept or Reject.'); return; }
    if (decision === 0 && !rejectReason) { setError('A reject reason is required.'); return; }
    setSaving(true); setError('');
    try {
      const saved = await authService.saveBlindDecision(taskId, selectedSlide.id, { decision, reject_reason: decision === 0 ? rejectReason : null });
      setSlides((current) => current.map((slide) => slide.id === selectedSlide.id ? { ...slide, blind_label: saved.blind_label, reject_reason: saved.reject_reason, final_status: saved.final_status } : slide));
      setMessage('Blind decision saved.');
    } catch (requestError) { setError(requestError.message); }
    finally { setSaving(false); }
  }

  if (loading) return <main className="admin-loading-page">Loading blind workspace...</main>;
  if (error && !slides.length) return <main className="admin-loading-page">{error}</main>;
  return <UserShell eyebrow="Blind Annotator" title="Blind Annotation Workspace" subtitle={`Task #${taskId}. Main annotation is hidden while you work.`} actions={<Link className="admin-action admin-action-secondary" to={`/tasks/${taskId}`}>← &nbsp;Back to task</Link>}>
    {error && <p className="auth-error">{error}</p>}{message && <p className="annotation-success">{message}</p>}
    {!slides.length ? <section className="admin-section">No processed slides are available for blind annotation.</section> : <div className="annotation-layout"><aside className="annotation-slide-list"><h2 className="admin-section-title">Slides</h2>{slides.map((slide, index) => <button className={`annotation-slide-item ${index === selectedIndex ? 'selected' : ''}`} key={slide.id} onClick={() => setSelectedIndex(index)} type="button"><span className="annotation-slide-check">{slide.blind_label === 1 ? '✓' : slide.blind_label === 0 ? '×' : '○'}</span><span>Page {String(slide.page_number).padStart(2, '0')}</span><small>{slide.image_id}</small></button>)}</aside><section className="annotation-preview"><img src={imageUrl} alt={selectedSlide.image_id} /><div><strong>{selectedSlide.image_id}</strong><span>Page {selectedSlide.page_number} of {slides.length}</span></div></section><section className="annotation-form"><div className="annotation-form-header"><div><h2 className="admin-section-title">Independent annotation</h2><p className="admin-muted">{selectedSlide.image_id}</p></div><span className="admin-status">MAIN ANSWER HIDDEN</span></div><label className="auth-label">Question<textarea className="auth-input admin-textarea" rows="3" value={form.question_text} onChange={update('question_text')} /></label>{isMultipleChoice && <div className="annotation-options">{['option_a', 'option_b', 'option_c', 'option_d'].map((field) => <label className="auth-label" key={field}>{field.replace('_', ' ').toUpperCase()}<input className="auth-input" value={form[field]} onChange={update(field)} /></label>)}</div>}<label className="auth-label">Answer{isMultipleChoice ? <select className="auth-input" value={form.answer} onChange={update('answer')}><option value="">Select answer</option>{['A', 'B', 'C', 'D'].map((answer) => <option key={answer}>{answer}</option>)}</select> : <textarea className="auth-input admin-textarea" rows="2" value={form.answer} onChange={update('answer')} />}</label><div className="annotation-form-actions"><button className="admin-action admin-action-primary" disabled={saving} onClick={save} type="button">{saving ? 'Saving...' : 'Save blind annotation'}</button><button className={`admin-action ${decision === 1 ? 'admin-action-primary' : 'admin-action-secondary'}`} disabled={saving} onClick={() => setDecision(1)} type="button">Accept</button><button className={`admin-action ${decision === 0 ? 'admin-action-primary' : 'admin-action-secondary'}`} disabled={saving} onClick={() => setDecision(0)} type="button">Reject</button></div>{decision === 0 && <label className="auth-label">Reject reason<select className="auth-input" value={rejectReason} onChange={(event) => setRejectReason(event.target.value)}><option value="">Select a reason</option><option value="CONTENT_MISMATCH">Content mismatch</option><option value="SPELLING_ERROR">Spelling error</option><option value="FORMAT_ERROR">Format error</option><option value="OTHER">Other</option></select></label>}<button className="admin-action admin-action-primary" style={{ marginTop: 18 }} disabled={saving} onClick={saveDecision} type="button">{saving ? 'Saving...' : 'Save blind decision'}</button>{selectedSlide.similarity_score != null && <p className="annotation-readonly">Comparison similarity: <strong>{selectedSlide.similarity_score}</strong></p>}</section></div>}
  </UserShell>;
}
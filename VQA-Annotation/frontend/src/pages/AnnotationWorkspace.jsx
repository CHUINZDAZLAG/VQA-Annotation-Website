import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import UserShell from "../components/UserShell";
import { authService } from "../services/authService";

const categories = {
  1: "TEXT_ONLY",
  2: "CHART_ONLY",
  3: "TABLE_ONLY",
  4: "MIXED",
};
const slideTypes = {
  1: "BUSINESS_AND_MARKETING_SLIDE",
  2: "BUSINESS_STARTUP_TRAINING_SLIDE",
  3: "STARTUP_COMPETITION_SLIDE",
};
const languages = { 1: "English", 2: "Vietnamese" };

function blankForm(outputType) {
  return {
    categories: 1,
    slide_type: 1,
    language: 1,
    question: {
      question_text: "",
      option_a: "",
      option_b: "",
      option_c: "",
      option_d: "",
    },
    answer: "",
    insight: "",
    prompt: "",
    question_type: outputType,
  };
}

function formFromSlide(slide, outputType) {
  if (!slide?.annotation) return blankForm(outputType);
  const empty = blankForm(outputType);
  return {
    ...empty,
    ...slide.annotation,
    question: { ...empty.question, ...(slide.annotation.question || {}) },
  };
}

export default function AnnotationWorkspace() {
  const { taskId } = useParams();
  const [task, setTask] = useState(null);
  const [slides, setSlides] = useState([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [form, setForm] = useState(null);
  const [imageUrl, setImageUrl] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [slideName, setSlideName] = useState("");
  const [driveFolderId, setDriveFolderId] = useState("");
  const [drivePdfs, setDrivePdfs] = useState([]);
  const [selectedPdfId, setSelectedPdfId] = useState("");
  const [driveLink, setDriveLink] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const selectedSlide = slides[selectedIndex];
  const isMultipleChoice = task?.output_type === "MULTIPLE_CHOICE";
  const completedCount = slides.filter(
    (slide) => slide.status === "COMPLETED",
  ).length;
  const progress = slides.length
    ? Math.round((completedCount / slides.length) * 100)
    : 0;

  async function load() {
    try {
      setLoading(true);
      setError("");
      const taskValue = await authService.getTask(taskId);
      setTask(taskValue);
      setDriveLink(taskValue.drive_link || taskValue.drive_folder_url || "");
      try {
        const slideValues = await authService.getTaskSlides(taskId);
        setSlides(slideValues);
        setSlideName(slideValues[0]?.slide_name || "");
      } catch (slideError) {
        if (!slideError.message.toLowerCase().includes("no document"))
          throw slideError;
        setSlides([]);
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
  }, [taskId]);
  useEffect(() => {
    let active = true;
    if (!selectedSlide || !task) return undefined;
    setForm(formFromSlide(selectedSlide, task.output_type));
    authService
      .getTaskSlideImage(taskId, selectedSlide.id)
      .then((url) => {
        if (active) setImageUrl(url);
        else URL.revokeObjectURL(url);
      })
      .catch((requestError) => active && setError(requestError.message));
    return () => {
      active = false;
    };
  }, [selectedIndex, selectedSlide?.id, task?.output_type, taskId]);

  const updateField = (field) => (event) =>
    setForm((current) => ({ ...current, [field]: event.target.value }));
  const updateQuestion = (field) => (event) =>
    setForm((current) => ({
      ...current,
      question: { ...current.question, [field]: event.target.value },
    }));
  function validate() {
    if (!form?.question.question_text.trim())
      return "Question text is required.";
    if (isMultipleChoice) {
      const missing = ["option_a", "option_b", "option_c", "option_d"].find(
        (key) => !form.question[key].trim(),
      );
      if (missing) return `${missing.replace("_", " ")} is required.`;
      if (!["A", "B", "C", "D"].includes(form.answer))
        return "Answer must be A, B, C, or D.";
    } else if (!form.answer.trim()) return "Answer is required.";
    return null;
  }
  async function saveCurrent(showMessage = true) {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return false;
    }
    setSaving(true);
    try {
      const saved = await authService.saveTaskSlideAnnotation(
        taskId,
        selectedSlide.id,
        {
          categories: Number(form.categories),
          slide_type: Number(form.slide_type),
          language: Number(form.language),
          question: form.question,
          answer: form.answer,
          insight: form.insight,
          prompt: form.prompt,
          edit_answer: form.edit_answer !== false,
        },
      );
      setSlides((current) =>
        current.map((slide) =>
          slide.id === selectedSlide.id
            ? { ...slide, status: saved.status, annotation: saved }
            : slide,
        ),
      );
      if (showMessage) setMessage("Annotation saved.");
      setError("");
      return true;
    } catch (requestError) {
      setError(requestError.message);
      return false;
    } finally {
      setSaving(false);
    }
  }
  async function generateCurrent() {
    if (!selectedSlide) return;
    setGenerating(true);
    setError("");
    setMessage("");
    try {
      const generated = await authService.generateTaskSlideAnnotation(
        taskId,
        selectedSlide.id,
        {
          prompt: form.prompt || null,
          language: Number(form.language),
          edit_answer: form.edit_answer !== false,
        },
      );
      setForm(formFromSlide({ annotation: generated }, task.output_type));
      setSlides((current) =>
        current.map((slide) =>
          slide.id === selectedSlide.id
            ? { ...slide, status: generated.status, annotation: generated }
            : slide,
        ),
      );
      setMessage(
        "Gemini annotation generated. Review it before saving or moving on.",
      );
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setGenerating(false);
    }
  }
  async function move(offset) {
    if (!(await saveCurrent(false))) return;
    setMessage("");
    setSelectedIndex((current) => current + offset);
  }
  async function selectSlide(index) {
    if (index === selectedIndex) return;
    if (!(await saveCurrent(false))) return;
    setMessage("");
    setSelectedIndex(index);
  }
  async function uploadDocument(event) {
    event.preventDefault();
    if (!uploadFile) {
      setError("Choose a PDF file first.");
      return;
    }
    if (!slideName.trim()) {
      setError("Slide name is required.");
      return;
    }
    setSaving(true);
    try {
      const response = await authService.uploadTaskDocument(
        taskId,
        uploadFile,
        slideName,
      );
      setSlides(response.slides);
      setSelectedIndex(0);
      setMessage("PDF processed successfully.");
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }
  async function listDrivePdfs(event) {
    event.preventDefault();
    if (!driveFolderId.trim()) {
      setError("Google Drive folder ID or link is required.");
      return;
    }
    setSaving(true);
    try {
      const files = await authService.listTaskDrivePdfs(
        taskId,
        driveFolderId.trim(),
      );
      setDrivePdfs(files);
      setSelectedPdfId(files[0]?.id || "");
      setError("");
      setMessage(`${files.length} PDF file(s) found.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }
  async function processDrivePdf(event) {
    event.preventDefault();
    if (!selectedPdfId || !slideName.trim()) {
      setError("Select a PDF and enter a slide name.");
      return;
    }
    setSaving(true);
    try {
      const response = await authService.processTaskDrivePdf(taskId, {
        folder_id: driveFolderId.trim(),
        pdf_file_id: selectedPdfId,
        slide_name: slideName.trim(),
      });
      setSlides(response.slides);
      setSelectedIndex(0);
      setMessage("Google Drive PDF processed successfully.");
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }
  async function saveDriveLink(event) {
    event.preventDefault();
    if (!driveLink.trim()) {
      setError("Google Drive link is required.");
      return;
    }
    setSaving(true);
    try {
      const saved = await authService.saveTaskDriveLink(
        taskId,
        driveLink.trim(),
      );
      setDriveLink(saved.drive_link);
      setTask((current) => ({
        ...current,
        drive_folder_url: saved.drive_link,
      }));
      setMessage("Google Drive link saved.");
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }
  async function submit() {
    if (completedCount !== slides.length) {
      setError(
        `Complete all slides before submitting (${completedCount} of ${slides.length}).`,
      );
      return;
    }
    try {
      await authService.submitTaskAnnotation(taskId);
      setTask((current) => ({ ...current, status: "SUBMITTED" }));
      setMessage("Annotation document submitted successfully.");
    } catch (requestError) {
      setError(requestError.message);
    }
  }
  const uploadView = useMemo(
    () => (
      <section className="admin-form-card annotation-upload-card">
        <p className="admin-eyebrow">Document processing</p>
        <h2
          className="admin-section-title"
          style={{ marginTop: 6, fontSize: 20 }}
        >
          {slides.length ? "Update PDF" : "Upload PDF"}
        </h2>
        <p className="admin-subtitle">
          The PDF remains associated with this task when replaced.
        </p>
        <form onSubmit={uploadDocument}>
          <label className="auth-label">
            PDF document
            <input
              className="auth-input"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) =>
                setUploadFile(event.target.files?.[0] || null)
              }
            />
          </label>
          <label className="auth-label">
            Slide name
            <input
              className="auth-input"
              placeholder="BusinessTraining"
              value={slideName}
              onChange={(event) => setSlideName(event.target.value)}
            />
          </label>
          <button
            className="admin-action admin-action-primary"
            style={{ marginTop: 24 }}
            disabled={saving}
            type="submit"
          >
            {saving
              ? "Processing..."
              : `${slides.length ? "Update" : "Upload"} & Process PDF →`}
          </button>
        </form>
      </section>
    ),
    [slideName, uploadFile, saving, slides.length],
  );
  const driveView = useMemo(
    () => (
      <section className="admin-form-card annotation-upload-card">
        <p className="admin-eyebrow">Google Drive source</p>
        <h2
          className="admin-section-title"
          style={{ marginTop: 6, fontSize: 20 }}
        >
          Select PDF from Drive
        </h2>
        <form onSubmit={listDrivePdfs}>
          <label className="auth-label">
            Folder ID or link
            <input
              className="auth-input"
              value={driveFolderId}
              onChange={(event) => setDriveFolderId(event.target.value)}
              placeholder="https://drive.google.com/drive/folders/..."
            />
          </label>
          <button
            className="admin-action admin-action-secondary"
            style={{ marginTop: 18 }}
            disabled={saving}
            type="submit"
          >
            List PDFs
          </button>
        </form>
        {drivePdfs.length > 0 && (
          <form onSubmit={processDrivePdf}>
            <label className="auth-label">
              PDF file
              <select
                className="auth-input"
                value={selectedPdfId}
                onChange={(event) => setSelectedPdfId(event.target.value)}
              >
                {drivePdfs.map((file) => (
                  <option value={file.id} key={file.id}>
                    {file.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="auth-label">
              Slide name
              <input
                className="auth-input"
                value={slideName}
                onChange={(event) => setSlideName(event.target.value)}
                placeholder="cake"
                required
              />
            </label>
            <button
              className="admin-action admin-action-primary"
              style={{ marginTop: 18 }}
              disabled={saving}
              type="submit"
            >
              {saving ? "Processing..." : "Process selected PDF →"}
            </button>
          </form>
        )}
      </section>
    ),
    [driveFolderId, drivePdfs, selectedPdfId, slideName, saving],
  );
  if (loading || (slides.length > 0 && !form))
    return (
      <main className="admin-loading-page">
        Loading annotation workspace...
      </main>
    );
  return (
    <UserShell
      eyebrow="Main Annotator"
      title={task?.name || `Task #${taskId}`}
      subtitle={`Status: ${task?.status || "-"} · Main annotation progress`}
      actions={
        <Link
          className="admin-action admin-action-secondary"
          to={`/tasks/${taskId}`}
        >
          ← &nbsp;Back to task
        </Link>
      }
    >
      {error && (
        <p className="auth-error" style={{ marginTop: 18 }}>
          {error}
        </p>
      )}
      {message && <p className="annotation-success">{message}</p>}
      {!slides.length ? (
        <>
          <div className="annotation-toolbar">
            {driveView}
            {uploadView}
          </div>
        </>
      ) : (
        <>
          <div className="annotation-toolbar">
            {driveView}
            <form
              className="admin-form-card annotation-upload-card"
              onSubmit={saveDriveLink}
            >
              <p className="admin-eyebrow">Extracted images</p>
              <h2
                className="admin-section-title"
                style={{ marginTop: 6, fontSize: 20 }}
              >
                Google Drive link
              </h2>
              <label className="auth-label">
                Drive URL
                <input
                  className="auth-input"
                  type="url"
                  value={driveLink}
                  onChange={(event) => setDriveLink(event.target.value)}
                  placeholder="https://drive.google.com/..."
                  required
                />
              </label>
              <button
                className="admin-action admin-action-secondary"
                style={{ marginTop: 24 }}
                disabled={saving}
                type="submit"
              >
                Save Drive Link
              </button>
            </form>
          </div>
          <div className="annotation-progress">
            <div>
              <strong>Annotation Progress</strong>
              <span>
                {completedCount} / {slides.length} slides completed
              </span>
            </div>
            <div className="annotation-progress-track">
              <span style={{ width: `${progress}%` }} />
            </div>
          </div>
          <div className="annotation-layout">
            <aside className="annotation-slide-list">
              <h2 className="admin-section-title">Slides</h2>
              {slides.map((slide, index) => (
                <button
                  className={`annotation-slide-item ${index === selectedIndex ? "selected" : ""}`}
                  key={slide.id}
                  onClick={() => selectSlide(index)}
                  type="button"
                >
                  <span className="annotation-slide-check">
                    {slide.status === "COMPLETED"
                      ? "✓"
                      : index === selectedIndex
                        ? "●"
                        : "○"}
                  </span>
                  <span>Page {String(slide.page_number).padStart(2, "0")}</span>
                  <small>{slide.image_id}</small>
                </button>
              ))}
            </aside>
            <section className="annotation-preview">
              <img src={imageUrl} alt={selectedSlide.image_id} />
              <div>
                <strong>{selectedSlide.image_id}</strong>
                <span>
                  Page {selectedSlide.page_number} of {slides.length}
                </span>
              </div>
            </section>
            <form
              className="annotation-form"
              onSubmit={(event) => {
                event.preventDefault();
                saveCurrent();
              }}
            >
              <div className="annotation-form-header">
                <div>
                  <h2 className="admin-section-title">Annotation</h2>
                  <p className="admin-muted">{selectedSlide.image_id}</p>
                </div>
                <span className="admin-status">{task.output_type}</span>
              </div>
              <div className="annotation-meta-grid">
                <label className="auth-label">
                  Category
                  <select
                    className="auth-input"
                    value={form.categories}
                    onChange={updateField("categories")}
                  >
                    {Object.entries(categories).map(([value, label]) => (
                      <option value={value} key={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="auth-label">
                  Slide Type
                  <select
                    className="auth-input"
                    value={form.slide_type}
                    onChange={updateField("slide_type")}
                  >
                    {Object.entries(slideTypes).map(([value, label]) => (
                      <option value={value} key={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="auth-label">
                  Language
                  <select
                    className="auth-input"
                    value={form.language}
                    onChange={updateField("language")}
                  >
                    {Object.entries(languages).map(([value, label]) => (
                      <option value={value} key={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <p className="annotation-readonly">
                Question Type: <strong>{task.output_type}</strong>
              </p>
              <label className="auth-label">
                Gemini prompt (optional)
                <textarea
                  className="auth-input admin-textarea"
                  rows="2"
                  value={form.prompt || ""}
                  onChange={updateField("prompt")}
                  placeholder="Create a concise question focused on the key takeaway."
                />
              </label>
              <div className="annotation-form-actions">
                <button
                  className="admin-action admin-action-secondary"
                  disabled={generating || saving}
                  onClick={generateCurrent}
                  type="button"
                >
                  {generating
                    ? "Generating..."
                    : selectedSlide.annotation
                      ? "Regenerate with Gemini"
                      : "Generate with Gemini"}
                </button>
                <label className="annotation-readonly">
                  <input
                    type="checkbox"
                    checked={form.edit_answer !== false}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        edit_answer: event.target.checked,
                      }))
                    }
                  />{" "}
                  Allow answer editing
                </label>
              </div>
              <label className="auth-label">
                Question
                <textarea
                  className="auth-input admin-textarea"
                  rows="3"
                  value={form.question.question_text}
                  onChange={updateQuestion("question_text")}
                />
              </label>
              {isMultipleChoice && (
                <div className="annotation-options">
                  {["option_a", "option_b", "option_c", "option_d"].map(
                    (option) => (
                      <label className="auth-label" key={option}>
                        {option.replace("_", " ").toUpperCase()}
                        <input
                          className="auth-input"
                          value={form.question[option]}
                          onChange={updateQuestion(option)}
                        />
                      </label>
                    ),
                  )}
                </div>
              )}
              <label className="auth-label">
                Answer
                {isMultipleChoice ? (
                  <select
                    className="auth-input"
                    value={form.answer}
                    disabled={form.edit_answer === false}
                    onChange={updateField("answer")}
                  >
                    <option value="">Select answer</option>
                    {["A", "B", "C", "D"].map((answer) => (
                      <option key={answer}>{answer}</option>
                    ))}
                  </select>
                ) : (
                  <textarea
                    className="auth-input admin-textarea"
                    rows="2"
                    value={form.answer}
                    disabled={form.edit_answer === false}
                    onChange={updateField("answer")}
                  />
                )}
              </label>
              <div className="annotation-form-actions">
                <button
                  className="admin-action admin-action-secondary"
                  disabled={selectedIndex === 0 || saving}
                  onClick={() => move(-1)}
                  type="button"
                >
                  ← Previous
                </button>
                <button
                  className="admin-action admin-action-primary"
                  disabled={saving}
                  type="submit"
                >
                  {saving ? "Saving..." : "Save Annotation"}
                </button>
                <button
                  className="admin-action admin-action-secondary"
                  disabled={selectedIndex === slides.length - 1 || saving}
                  onClick={() => move(1)}
                  type="button"
                >
                  Next →
                </button>
              </div>
            </form>
          </div>
          <div className="annotation-submit">
            <span>
              {completedCount} of {slides.length} slides completed.
            </span>
            <button
              className="admin-action admin-action-primary"
              disabled={
                completedCount !== slides.length || task.status === "SUBMITTED"
              }
              onClick={submit}
              type="button"
            >
              {task.status === "SUBMITTED" ? "Submitted" : "Submit Annotation"}
            </button>
          </div>
        </>
      )}
    </UserShell>
  );
}

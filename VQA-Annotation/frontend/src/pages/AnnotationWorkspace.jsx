import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import UserShell from "../components/UserShell";
import { authService } from "../services/authService";

const categories = {
  0: "CHART_ONLY",
  1: "TEXT_ONLY",
  2: "TABLE_ONLY",
  3: "MIXED",
  4: "INSIGHT",
};
const slideTypes = {
  1: "BUSINESS_AND_MARKETING_SLIDE",
  2: "BUSINESS_STARTUP_TRAINING_SLIDE",
  3: "STARTUP_COMPETITION_SLIDE",
};
const languages = { 1: "English", 2: "Vietnamese" };
const categoryValues = Object.fromEntries(
  Object.entries(categories).map(([value, label]) => [label, Number(value)]),
);
const slideTypeValues = Object.fromEntries(
  Object.entries(slideTypes).map(([value, label]) => [label, Number(value)]),
);
const languageValues = { ENGLISH: 1, VIETNAMESE: 2 };

function manualJsonTemplate(outputType) {
  const question = outputType === "MULTIPLE_CHOICE"
    ? { question_text: "", option_a: "", option_b: "", option_c: "", option_d: "" }
    : { question_text: "" };
  return JSON.stringify({
    annotations: Array.from({ length: 10 }, (_, index) => ({
      category: index % 5,
      slide_type: 1,
      language: 1,
      question,
      answer: "",
    })),
  }, null, 2);
}

function normalizeEnum(value, names, fallback, field) {
  if (value == null || value === "") return fallback;
  if (typeof value === "number" || /^\d+$/.test(String(value))) return Number(value);
  const normalized = names[String(value).trim().toUpperCase()];
  if (normalized == null) throw new Error(`Unknown ${field} value: ${value}`);
  return normalized;
}

function normalizeImportedAnnotation(annotation, outputType) {
  if (!annotation || typeof annotation !== "object" || Array.isArray(annotation)) {
    throw new Error("Each annotation must be a JSON object.");
  }
  const rawQuestion = annotation.question;
  const question = typeof rawQuestion === "string"
    ? { question_text: rawQuestion }
    : { ...(rawQuestion || {}) };
  if (outputType === "MULTIPLE_CHOICE") {
    for (const letter of ["a", "b", "c", "d"]) {
      question[`option_${letter}`] = question[`option_${letter}`] ?? question[`option_${letter.toUpperCase()}`] ?? "";
      delete question[`option_${letter.toUpperCase()}`];
    }
  }
  return {
    categories: normalizeEnum(annotation.categories ?? annotation.category, categoryValues, 0, "category"),
    slide_type: normalizeEnum(annotation.slide_type, slideTypeValues, 1, "slide_type"),
    language: normalizeEnum(annotation.language, languageValues, 1, "language"),
    question,
    answer: String(annotation.answer ?? "").trim(),
    insight: annotation.insight == null ? null : String(annotation.insight),
    prompt: null,
    edit_answer: annotation.edit_answer !== false,
  };
}

function blankForm(outputType) {
  return {
    categories: 0,
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

function formFromAnnotation(annotation, outputType) {
  if (!annotation) return blankForm(outputType);
  const empty = blankForm(outputType);
  return {
    ...empty,
    ...annotation,
    annotation_id: annotation.id,
    question: { ...empty.question, ...(annotation.question || {}) },
  };
}

export default function AnnotationWorkspace() {
  const { taskId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [task, setTask] = useState(null);
  const [slides, setSlides] = useState([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [selectedAnnotationIndex, setSelectedAnnotationIndex] = useState(0);
  const [form, setForm] = useState(null);
  const [formDirty, setFormDirty] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [slideName, setSlideName] = useState("");
  const [sourceMode, setSourceMode] = useState("UPLOAD");
  const [driveFolderId, setDriveFolderId] = useState("");
  const [driveSourceFolderId, setDriveSourceFolderId] = useState("");
  const [drivePdfInput, setDrivePdfInput] = useState("");
  const [drivePdfs, setDrivePdfs] = useState([]);
  const [selectedPdfId, setSelectedPdfId] = useState("");
  const [driveLink, setDriveLink] = useState("");
  const [driveConnection, setDriveConnection] = useState({ connected: false, account_email: null });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [creationMode, setCreationMode] = useState("GEMINI");
  const [manualJson, setManualJson] = useState("");
  const [expandedRows, setExpandedRows] = useState(() => new Set());
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const selectedSlide = slides[selectedIndex];
  const selectedAnnotations = selectedSlide?.annotations || [];
  const selectedAnnotation = selectedAnnotations[selectedAnnotationIndex] || null;
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
      setDriveFolderId(taskValue.annotator_drive_folder_id || taskValue.admin_drive_folder_id || taskValue.drive_folder_id || "");
      try {
        const slideValues = await authService.getTaskSlides(taskId);
        setSlides(slideValues);
        const resumeIndex = slideValues.findIndex((slide) => slide.id === taskValue.current_slide_id);
        setSelectedIndex(resumeIndex >= 0 ? resumeIndex : 0);
        setSelectedAnnotationIndex(0);
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
    const driveStatus = searchParams.get("drive");
    const driveDetail = searchParams.get("detail");
    authService.getGoogleDriveConnection()
      .then((connection) => {
        setDriveConnection(connection);
        if (driveStatus === "connected") setMessage("Google Drive connected successfully.");
      })
      .catch((requestError) => setError(requestError.message));
    if (driveStatus === "error") setError(driveDetail || "Google Drive connection failed.");
    if (driveStatus) setSearchParams({}, { replace: true });
  }, [searchParams, setSearchParams]);
  useEffect(() => {
    let active = true;
    let loadedImageUrl = "";
    if (!selectedSlide || !task) return undefined;
    setSelectedAnnotationIndex(0);
    setExpandedRows(new Set());
    setForm(formFromAnnotation(selectedSlide.annotations?.[0], task.output_type));
    setFormDirty(false);
    authService.saveTaskDraftPosition(taskId, selectedSlide.id).catch(() => {});
    authService
      .getTaskSlideImage(taskId, selectedSlide.id)
      .then((url) => {
        loadedImageUrl = url;
        if (active) setImageUrl(url);
        else URL.revokeObjectURL(url);
      })
      .catch((requestError) => active && setError(requestError.message));
    return () => {
      active = false;
      if (loadedImageUrl) URL.revokeObjectURL(loadedImageUrl);
    };
  }, [selectedIndex, selectedSlide?.id, task?.output_type, taskId]);

  useEffect(() => {
    if (!selectedSlide || !task) return;
    if (formDirty) return;
    setForm(formFromAnnotation(selectedAnnotation, task.output_type));
    setFormDirty(false);
  }, [selectedAnnotationIndex, selectedAnnotation?.id, selectedSlide?.id, task?.output_type]);

  useEffect(() => {
    if (!form?.annotation_id || !formDirty || saving || generating) return undefined;
    const timer = window.setTimeout(() => saveCurrent(false), 900);
    return () => window.clearTimeout(timer);
  }, [form, formDirty, selectedSlide?.id]);

  const updateField = (field) => (event) => {
    setFormDirty(true);
    setForm((current) => ({ ...current, [field]: event.target.value }));
  };
  async function updateInlineAnnotation(annotationIndex, update) {
    const annotation = selectedAnnotations[annotationIndex];
    if (!annotation) return;
    if (annotationIndex !== selectedAnnotationIndex && formDirty) {
      const saved = await saveCurrent(false);
      if (!saved) return;
    }
    const updated = update(formFromAnnotation(annotation, task.output_type));
    updateSelectedSlide(updated, annotationIndex);
    setSelectedAnnotationIndex(annotationIndex);
    setForm(updated);
    setFormDirty(true);
  }
  const updateInlineField = (annotationIndex, field) => (event) => {
    const value = event.target.value;
    updateInlineAnnotation(annotationIndex, (annotation) => ({
      ...annotation,
      [field]: value,
    }));
  };
  const updateInlineQuestion = (annotationIndex, field) => (event) => {
    const value = event.target.value;
    updateInlineAnnotation(annotationIndex, (annotation) => ({
      ...annotation,
      question: { ...annotation.question, [field]: value },
    }));
  };
  function updateSelectedSlide(annotation, annotationIndex = selectedAnnotationIndex) {
    setSlides((current) =>
      current.map((slide) => {
        if (slide.id !== selectedSlide.id) return slide;
        const annotations = [...(slide.annotations || [])];
        annotations[annotationIndex] = annotation;
        return {
          ...slide,
          annotations,
          annotation: annotations[0] || null,
          status: annotations.length === 10 && annotations.every((item) => item.status === "COMPLETED")
            ? "COMPLETED"
            : "IN_PROGRESS",
        };
      }),
    );
  }
  async function saveCurrent(showMessage = true) {
    if (!selectedSlide || !form) return true;
    setSaving(true);
    try {
      const saved = await authService.saveTaskSlideAnnotation(
        taskId,
        selectedSlide.id,
        {
          annotation_id: form.annotation_id || null,
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
      updateSelectedSlide(saved);
      setForm(formFromAnnotation(saved, task.output_type));
      setFormDirty(false);
      if (showMessage) setMessage(saved.status === "COMPLETED" ? "Draft saved." : "Incomplete draft saved.");
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
      const generatedAnnotations = await authService.generateTaskSlideAnnotation(
        taskId,
        selectedSlide.id,
        {
          prompt: form.prompt || null,
          language: Number(form.language),
          category: Number(form.categories),
          edit_answer: form.edit_answer !== false,
        },
      );
      setSlides((current) => current.map((slide) => slide.id === selectedSlide.id
        ? {
            ...slide,
            annotations: generatedAnnotations,
            annotation: generatedAnnotations[0] || null,
            status: generatedAnnotations.every((annotation) => annotation.status === "COMPLETED")
              ? "COMPLETED"
              : "IN_PROGRESS",
          }
        : slide));
      setSelectedAnnotationIndex(0);
      setForm(formFromAnnotation(generatedAnnotations[0], task.output_type));
      setFormDirty(false);
      setMessage(
        "Gemini generated 10 labels for this slide. Review the table before publishing.",
      );
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setGenerating(false);
    }
  }
  async function importCurrentJson() {
    if (!selectedSlide) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const parsed = JSON.parse(manualJson);
      const items = Array.isArray(parsed) ? parsed : parsed.annotations;
      if (!Array.isArray(items) || items.length !== 10) {
        throw new Error('JSON must be an array of 10 labels or an object with exactly 10 items in "annotations".');
      }
      const importedAnnotations = await authService.importTaskSlideAnnotations(
        taskId,
        selectedSlide.id,
        items.map((item) => normalizeImportedAnnotation(item, task.output_type)),
      );
      setSlides((current) => current.map((slide) => slide.id === selectedSlide.id
        ? {
            ...slide,
            annotations: importedAnnotations,
            annotation: importedAnnotations[0] || null,
            status: importedAnnotations.every((annotation) => annotation.status === "COMPLETED")
              ? "COMPLETED"
              : "IN_PROGRESS",
          }
        : slide));
      setSelectedAnnotationIndex(0);
      setForm(formFromAnnotation(importedAnnotations[0], task.output_type));
      setFormDirty(false);
      setExpandedRows(new Set());
      setMessage("10 JSON labels imported as drafts. Open any row to review or edit it.");
    } catch (requestError) {
      setError(requestError instanceof SyntaxError
        ? `Invalid JSON: ${requestError.message}`
        : requestError.message);
    } finally {
      setSaving(false);
    }
  }
  async function toggleRow(index) {
    const isExpanded = expandedRows.has(index);
    if (!isExpanded && index !== selectedAnnotationIndex && !(await saveCurrent(false))) return;
    setExpandedRows((current) => {
      const next = new Set(current);
      if (isExpanded) next.delete(index);
      else next.add(index);
      return next;
    });
    if (!isExpanded) setSelectedAnnotationIndex(index);
  }
  async function saveLabel(index) {
    if (index !== selectedAnnotationIndex) {
      setError("Select or edit this label before saving it.");
      return;
    }
    await saveCurrent(true);
  }
  async function deleteAnnotation() {
    if (!selectedAnnotation?.id) return;
    setSaving(true);
    setError("");
    try {
      await authService.deleteTaskSlideAnnotation(taskId, selectedSlide.id, selectedAnnotation.id);
      const annotations = selectedAnnotations.filter((item) => item.id !== selectedAnnotation.id);
      setSlides((current) => current.map((slide) => slide.id === selectedSlide.id
        ? {
            ...slide,
            annotations,
            annotation: annotations[0] || null,
            status: annotations.length === 10 && annotations.every((item) => item.status === "COMPLETED")
              ? "COMPLETED"
              : "IN_PROGRESS",
          }
        : slide));
      const nextIndex = Math.max(0, selectedAnnotationIndex - 1);
      setSelectedAnnotationIndex(nextIndex);
      setForm(formFromAnnotation(annotations[nextIndex], task.output_type));
      setFormDirty(false);
      setMessage("Draft annotation deleted.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
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
  async function selectAnnotation(index) {
    if (index === selectedAnnotationIndex) return;
    if (!(await saveCurrent(false))) return;
    setSelectedAnnotationIndex(index);
  }
  async function uploadDocument(event) {
    event.preventDefault();
    if (!driveConnection.connected) {
      setError("Connect Google Drive before uploading and processing a PDF.");
      return;
    }
    if (!uploadFile) {
      setError("Choose a PDF file first.");
      return;
    }
    if (!slideName.trim()) {
      setError("Slide name is required.");
      return;
    }
    if (!driveFolderId.trim()) {
      setError("Destination Google Drive folder is required.");
      return;
    }
    setSaving(true);
    try {
      const response = await authService.uploadTaskDocument(
        taskId,
        uploadFile,
        slideName,
        driveFolderId.trim(),
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
    if (!driveConnection.connected) {
      setError("Connect Google Drive before listing Drive files.");
      return;
    }
    if (!driveSourceFolderId.trim()) {
      setError("Enter a source Drive folder to list its PDFs.");
      return;
    }
    setSaving(true);
    try {
      const files = await authService.listTaskDrivePdfs(
        taskId,
        driveSourceFolderId.trim(),
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
    if (!driveConnection.connected) {
      setError("Connect Google Drive before processing a Drive PDF.");
      return;
    }
    const pdfFileId = drivePdfInput.trim() || selectedPdfId;
    if (!pdfFileId || !slideName.trim() || !driveFolderId.trim()) {
      setError("Enter a Drive PDF, slide name, and destination Drive folder.");
      return;
    }
    setSaving(true);
    try {
      const response = await authService.processTaskDrivePdf(taskId, {
        folder_id: driveSourceFolderId.trim() || driveFolderId.trim(),
        pdf_file_id: pdfFileId,
        destination_folder_id: driveFolderId.trim(),
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
  async function connectGoogleDrive() {
    try {
      setError("");
      const { authorization_url: authorizationUrl } = await authService.startGoogleDriveConnection(
        `/tasks/${taskId}/annotate`,
      );
      window.location.assign(authorizationUrl);
    } catch (requestError) {
      setError(requestError.message);
    }
  }
  async function submit() {
    if (completedCount !== slides.length) {
      setError(
        `Complete all slides before submitting (${completedCount} of ${slides.length}).`,
      );
      return;
    }
    if (!(await saveCurrent(false))) return;
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
          Every generated page image is uploaded to the destination folder immediately.
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
          <label className="auth-label">
            Destination Google Drive folder
            <input
              className="auth-input"
              value={driveFolderId}
              onChange={(event) => setDriveFolderId(event.target.value)}
              placeholder="Folder ID or https://drive.google.com/drive/folders/..."
              required
            />
          </label>
          <button
            className="admin-action admin-action-primary"
            style={{ marginTop: 24 }}
            disabled={saving || !driveConnection.connected}
            type="submit"
          >
            {saving
              ? "Processing..."
              : `${slides.length ? "Update" : "Upload"} & Process PDF →`}
          </button>
        </form>
      </section>
    ),
    [slideName, uploadFile, driveFolderId, saving, slides.length, driveConnection.connected],
  );
  const driveView = useMemo(
    () => (
      <section className="admin-form-card annotation-upload-card">
        <p className="admin-eyebrow">Google Drive source</p>
        <h2
          className="admin-section-title"
          style={{ marginTop: 6, fontSize: 20 }}
        >
          Process PDF from Drive
        </h2>
        <form onSubmit={processDrivePdf}>
          <label className="auth-label">
            Source PDF URL or file ID
            <input
              className="auth-input"
              value={drivePdfInput}
              onChange={(event) => setDrivePdfInput(event.target.value)}
              placeholder="https://drive.google.com/file/d/.../view or FILE_ID"
            />
          </label>
          {drivePdfs.length > 0 && (
            <label className="auth-label">
              Or select a listed PDF
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
          )}
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
            <label className="auth-label">
              Destination Google Drive folder
              <input
                className="auth-input"
                value={driveFolderId}
                onChange={(event) => setDriveFolderId(event.target.value)}
                placeholder="Folder ID or folder URL"
                required
              />
            </label>
            <button
              className="admin-action admin-action-primary"
              style={{ marginTop: 18 }}
              disabled={saving || !driveConnection.connected}
              type="submit"
            >
              {saving ? "Processing..." : "Process selected PDF →"}
            </button>
        </form>
        <form onSubmit={listDrivePdfs}>
          <label className="auth-label">
            Optional source folder for listing PDFs
            <input
              className="auth-input"
              value={driveSourceFolderId}
              onChange={(event) => setDriveSourceFolderId(event.target.value)}
              placeholder="Source folder ID or URL"
            />
          </label>
          <button className="admin-action admin-action-secondary" disabled={saving || !driveConnection.connected} type="submit">
            List PDFs
          </button>
        </form>
      </section>
    ),
    [driveFolderId, driveSourceFolderId, drivePdfInput, drivePdfs, selectedPdfId, slideName, saving, driveConnection.connected],
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
      <div className={driveConnection.connected ? "annotation-success" : "auth-error"} style={{ marginTop: 18 }}>
        <span>
          {driveConnection.connected
            ? `Google Drive connected${driveConnection.account_email ? `: ${driveConnection.account_email}` : "."}`
            : "Connect Google Drive before using Drive files or folders."}
        </span>
        <button
          className="admin-action admin-action-secondary"
          onClick={connectGoogleDrive}
          style={{ marginLeft: 12 }}
          type="button"
        >
          {driveConnection.connected ? "Reconnect Drive" : "Connect Google Drive"}
        </button>
      </div>
      {error && (
        <p className="auth-error" style={{ marginTop: 18 }}>
          {error}
        </p>
      )}
      {message && <p className="annotation-success">{message}</p>}
      <div className="annotation-form-actions" style={{ justifyContent: "flex-start", marginTop: 18 }}>
        <button
          className={`admin-action ${sourceMode === "UPLOAD" ? "admin-action-primary" : "admin-action-secondary"}`}
          onClick={() => setSourceMode("UPLOAD")}
          type="button"
        >
          Upload PDF
        </button>
        <button
          className={`admin-action ${sourceMode === "DRIVE" ? "admin-action-primary" : "admin-action-secondary"}`}
          onClick={() => setSourceMode("DRIVE")}
          type="button"
        >
          Google Drive PDF
        </button>
      </div>
      {!slides.length ? (
        <div className="annotation-toolbar">
          {sourceMode === "UPLOAD" ? uploadView : driveView}
        </div>
      ) : (
        <>
          <div className="annotation-toolbar">
            {sourceMode === "UPLOAD" ? uploadView : driveView}
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
          <div className="annotation-navigation">
            <button
              className="admin-action admin-action-secondary"
              disabled={selectedIndex === 0 || saving}
              onClick={() => move(-1)}
              type="button"
            >
              ← Previous
            </button>
            <label>
              Slide
              <select value={selectedIndex} onChange={(event) => selectSlide(Number(event.target.value))}>
                {slides.map((slide, index) => (
                  <option value={index} key={slide.id}>Page {slide.page_number} · {slide.image_id}</option>
                ))}
              </select>
            </label>
            <button
              className="admin-action admin-action-primary"
              disabled={selectedIndex === slides.length - 1 || saving}
              onClick={() => move(1)}
              type="button"
            >
              {saving ? "Saving..." : "Next →"}
            </button>
          </div>
          <div className="annotation-layout annotation-main-layout">
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
                  <h2 className="admin-section-title">Labels for current slide</h2>
                  <p className="admin-muted">{selectedAnnotations.length} / 10 labels · {selectedSlide.image_id}</p>
                </div>
                <span className="admin-status">{task.output_type}</span>
              </div>
              <div className="annotation-table-toolbar">
                <div className="annotation-creation-tabs" role="tablist" aria-label="Label creation method">
                  <button
                    aria-selected={creationMode === "GEMINI"}
                    className={creationMode === "GEMINI" ? "selected" : ""}
                    onClick={() => setCreationMode("GEMINI")}
                    role="tab"
                    type="button"
                  >
                    Gemini
                  </button>
                  <button
                    aria-selected={creationMode === "JSON"}
                    className={creationMode === "JSON" ? "selected" : ""}
                    onClick={() => {
                      setCreationMode("JSON");
                      if (!manualJson) setManualJson(manualJsonTemplate(task.output_type));
                    }}
                    role="tab"
                    type="button"
                  >
                    Paste JSON
                  </button>
                </div>
                {creationMode === "GEMINI" && (
                  <button className="admin-action admin-action-secondary" disabled={generating || saving} onClick={generateCurrent} type="button">
                    {generating ? "Generating 10 labels..." : selectedAnnotations.length ? "Regenerate 10 labels" : "Generate 10 labels with Gemini"}
                  </button>
                )}
              </div>
              {creationMode === "JSON" && (
                <div className="annotation-json-import">
                  <div>
                    <strong>Paste 10 labels as JSON</strong>
                    <span>Accepts an array or {`{ "annotations": [...] }`}. Category and metadata may use numeric IDs or enum names.</span>
                  </div>
                  <textarea
                    aria-label="JSON labels"
                    rows="12"
                    spellCheck="false"
                    value={manualJson}
                    onChange={(event) => setManualJson(event.target.value)}
                  />
                  <div className="annotation-json-import-actions">
                    <button className="admin-action admin-action-secondary" onClick={() => setManualJson(manualJsonTemplate(task.output_type))} type="button">
                      Reset template
                    </button>
                    <button className="admin-action admin-action-primary" disabled={saving} onClick={importCurrentJson} type="button">
                      {saving ? "Importing..." : "Import 10 labels"}
                    </button>
                  </div>
                </div>
              )}
              <div className="annotation-label-table-wrap">
                <table className="annotation-label-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Category</th>
                      <th>Question</th>
                      <th>Answer</th>
                      <th>Status</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {selectedAnnotations.map((annotation, index) => (
                      <React.Fragment key={annotation.id}>
                        <tr className={expandedRows.has(index) ? "selected" : ""}>
                          <td>{index + 1}</td>
                          <td><span className="annotation-category-chip">{categories[annotation.categories] || annotation.categories}</span></td>
                          <td><span className="annotation-question-summary">{annotation.question?.question_text || "Not entered"}</span></td>
                          <td><strong>{annotation.answer || "-"}</strong></td>
                          <td><span className={`annotation-label-status ${annotation.status === "COMPLETED" ? "complete" : ""}`}>{annotation.status === "COMPLETED" ? "Complete" : "In progress"}</span></td>
                          <td><button aria-expanded={expandedRows.has(index)} onClick={() => toggleRow(index)} type="button">{expandedRows.has(index) ? "Collapse" : "View full / Edit"}</button></td>
                        </tr>
                        {expandedRows.has(index) && (
                          <tr className="annotation-detail-row">
                            <td colSpan="6">
                              <div className="annotation-detail-editor">
                                <div className="annotation-inline-fields">
                                  <label>
                                    <span>category</span>
                                    <select value={annotation.categories} onChange={updateInlineField(index, "categories")}>
                                      {Object.entries(categories).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                                    </select>
                                  </label>
                                  <label>
                                    <span>slide_type</span>
                                    <select value={annotation.slide_type} onChange={updateInlineField(index, "slide_type")}>
                                      {Object.entries(slideTypes).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                                    </select>
                                  </label>
                                  <label>
                                    <span>language</span>
                                    <select value={annotation.language} onChange={updateInlineField(index, "language")}>
                                      {Object.entries(languages).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
                                    </select>
                                  </label>
                                </div>
                                <div className="annotation-json-editor">
                                  <label>
                                    <span>"question_text":</span>
                                    <textarea rows="3" value={annotation.question?.question_text || ""} onChange={updateInlineQuestion(index, "question_text")} />
                                  </label>
                                  {isMultipleChoice && ["option_a", "option_b", "option_c", "option_d"].map((option) => (
                                    <label key={option}>
                                      <span>"{option}":</span>
                                      <textarea rows="2" value={annotation.question?.[option] || ""} onChange={updateInlineQuestion(index, option)} />
                                    </label>
                                  ))}
                                </div>
                                <label className="annotation-detail-answer">
                                  <span>answer</span>
                                  {isMultipleChoice ? (
                                    <select className="annotation-inline-answer" value={annotation.answer || ""} disabled={annotation.edit_answer === false} onChange={updateInlineField(index, "answer")}>
                                      <option value="">Select</option>
                                      {["A", "B", "C", "D"].map((answer) => <option value={answer} key={answer}>{answer}</option>)}
                                    </select>
                                  ) : (
                                    <textarea className="annotation-inline-answer" rows="4" value={annotation.answer || ""} disabled={annotation.edit_answer === false} onChange={updateInlineField(index, "answer")} />
                                  )}
                                </label>
                                <div className="annotation-detail-actions">
                                  <button className="admin-action admin-action-secondary" onClick={() => toggleRow(index)} type="button">Collapse</button>
                                  <button className="admin-action admin-action-primary" disabled={saving} onClick={() => saveLabel(index)} type="button">{saving && index === selectedAnnotationIndex ? "Saving..." : "Save label"}</button>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
              {!selectedAnnotation && (
                <p className="annotation-empty">No labels exist for this slide. Generate 10 labels with Gemini or import 10 labels from JSON to start.</p>
              )}
              {selectedAnnotation && (
                <div className="annotation-row-actions">
                  <span>Editing annotation {selectedAnnotationIndex + 1} directly in the table · changes auto-save</span>
                  <button disabled={saving} onClick={deleteAnnotation} type="button">Delete</button>
                </div>
              )}
              {creationMode === "GEMINI" && (
                <label className="auth-label annotation-prompt-field">
                  Gemini prompt for the next 10-label generation (optional)
                  <textarea
                    className="auth-input admin-textarea"
                    rows="2"
                    value={form.prompt || ""}
                    onChange={updateField("prompt")}
                    placeholder="Create a concise question focused on the key takeaway."
                  />
                </label>
              )}
              <div className="annotation-form-actions">
                <label className="annotation-readonly">
                  <input
                    type="checkbox"
                    checked={form.edit_answer !== false}
                    onChange={(event) =>
                      {
                        setFormDirty(true);
                        setForm((current) => ({
                          ...current,
                          edit_answer: event.target.checked,
                        }));
                      }
                    }
                  />{" "}
                  Allow answer editing
                </label>
              </div>
              <div className="annotation-form-actions">
                <button
                  className="admin-action admin-action-primary"
                  disabled={saving}
                  type="submit"
                >
                  {saving ? "Saving..." : "Save Draft"}
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
              {task.status === "SUBMITTED" ? "Published" : "Publish Draft"}
            </button>
          </div>
        </>
      )}
    </UserShell>
  );
}

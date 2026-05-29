import { useState, useRef, useEffect } from "react";
import { api } from "../api.js";
import AudioPlayer from "./AudioPlayer.jsx";
import { useI18n } from "../i18n.jsx";

const STATUS_KEY = {
  queued: "statusQueued",
  running: "statusRunning",
  done: "statusDone",
  error: "statusError",
};

function fmtDur(s) {
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function fmtTime(t) {
  if (!t) return "";
  return new Date(t * 1000).toLocaleTimeString("ja-JP");
}

const DotsIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
    <circle cx="12" cy="5" r="1.8" />
    <circle cx="12" cy="12" r="1.8" />
    <circle cx="12" cy="19" r="1.8" />
  </svg>
);
const DownloadIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v11" />
    <path d="M7 10l5 5 5-5" />
    <path d="M5 20h14" />
  </svg>
);
const TrashIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16" />
    <path d="M9 7V5h6v2" />
    <path d="M6 7l1 13h10l1-13" />
  </svg>
);
const CopyIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V5a2 2 0 0 1 2-2h10" />
  </svg>
);

export default function ResultCard({ job, onDelete, onCopyToForm }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);

  const statusLabel = (s) => (STATUS_KEY[s] ? t(STATUS_KEY[s]) : s);

  const elapsed =
    job.finished_at && job.started_at
      ? (job.finished_at - job.started_at).toFixed(1)
      : null;

  // Close the menu when clicking outside it or pressing Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const canDownload = job.status === "done" && job.filename;

  return (
    <div className={`row-card status-${job.status}${open ? " menu-open" : ""}`}>
      <div className="row-main">
        <div className="row-title-line">
          <span className="row-title" title={job.prompt}>
            {job.prompt}
          </span>
          {job.status !== "done" && (
            <span className={`badge badge-${job.status}`}>
              {statusLabel(job.status)}
            </span>
          )}
        </div>

        <div className="row-desc">
          {fmtDur(job.seconds)} · {job.steps} steps · cfg {job.cfg_scale} · seed{" "}
          {job.seed}
          {elapsed && ` · ${elapsed}s`}
          {job.finished_at && ` · ${fmtTime(job.finished_at)}`}
        </div>

        <div className="row-actions">
          {(job.status === "queued" || job.status === "running") && (
            <div className="progress">
              <div className="spinner" />
              <span>{job.message || statusLabel(job.status)}</span>
            </div>
          )}

          {job.status === "error" && (
            <span className="card-error">{job.message}</span>
          )}

          {canDownload && <AudioPlayer src={api.audioUrl(job.id)} />}
        </div>
      </div>

      <div className="row-menu-wrap" ref={menuRef}>
        <button
          className="row-menu"
          title={t("menu")}
          onClick={() => setOpen((o) => !o)}
        >
          <DotsIcon />
        </button>

        {open && (
          <div className="menu-pop">
            <button
              className="menu-item"
              onClick={() => {
                setOpen(false);
                onCopyToForm(job);
              }}
            >
              <CopyIcon />
              {t("copyToForm")}
            </button>
            {canDownload && (
              <a
                className="menu-item"
                href={api.audioUrl(job.id)}
                download={`${job.id}.wav`}
                onClick={() => setOpen(false)}
              >
                <DownloadIcon />
                {t("download")}
              </a>
            )}
            <button
              className="menu-item danger"
              onClick={() => {
                setOpen(false);
                onDelete(job.id);
              }}
            >
              <TrashIcon />
              {t("delete")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

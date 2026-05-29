import { api } from "../api.js";
import AudioPlayer from "./AudioPlayer.jsx";

const STATUS_LABEL = {
  queued: "待機中",
  running: "生成中",
  done: "完了",
  error: "エラー",
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

export default function ResultCard({ job, onDelete }) {
  const elapsed =
    job.finished_at && job.started_at
      ? (job.finished_at - job.started_at).toFixed(1)
      : null;

  return (
    <div className={`row-card status-${job.status}`}>
      <div className="row-main">
        <div className="row-title-line">
          <span className="row-title" title={job.prompt}>
            {job.prompt}
          </span>
          <span className={`badge badge-${job.status}`}>
            {STATUS_LABEL[job.status] ?? job.status}
          </span>
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
              <span>{job.message || STATUS_LABEL[job.status]}</span>
            </div>
          )}

          {job.status === "error" && (
            <span className="card-error">{job.message}</span>
          )}

          {job.status === "done" && job.filename && (
            <>
              <AudioPlayer src={api.audioUrl(job.id)} />
              <a
                href={api.audioUrl(job.id)}
                download={`${job.id}.wav`}
                className="link dl-link"
                title="WAVをダウンロード"
              >
                <svg
                  viewBox="0 0 24 24"
                  width="17"
                  height="17"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 3v11" />
                  <path d="M7 10l5 5 5-5" />
                  <path d="M5 20h14" />
                </svg>
              </a>
            </>
          )}
        </div>
      </div>

      <button
        className="row-menu"
        title="削除"
        onClick={() => onDelete(job.id)}
      >
        ✕
      </button>
    </div>
  );
}

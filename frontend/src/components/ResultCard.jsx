import { api } from "../api.js";

const STATUS_LABEL = {
  queued: "待機中",
  running: "生成中",
  done: "完了",
  error: "エラー",
};

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
    <div className={`card status-${job.status}`}>
      <div className="card-head">
        <span className={`badge badge-${job.status}`}>
          {STATUS_LABEL[job.status] ?? job.status}
        </span>
        <button
          className="icon-btn"
          title="削除"
          onClick={() => onDelete(job.id)}
        >
          ✕
        </button>
      </div>

      <p className="card-prompt" title={job.prompt}>
        {job.prompt}
      </p>

      <div className="card-meta">
        <span>{job.seconds}s</span>
        <span>{job.steps} steps</span>
        <span>cfg {job.cfg_scale}</span>
        <span>seed {job.seed}</span>
      </div>

      {(job.status === "running" || job.status === "queued") && (
        <div className="progress">
          <div className="spinner" />
          <span>{job.message || STATUS_LABEL[job.status]}</span>
        </div>
      )}

      {job.status === "error" && (
        <p className="card-error">{job.message}</p>
      )}

      {job.status === "done" && job.filename && (
        <div className="card-audio">
          <audio controls src={api.audioUrl(job.id)} />
          <div className="card-foot">
            <a
              href={api.audioUrl(job.id)}
              download={`${job.id}.wav`}
              className="link"
            >
              ⬇ WAV保存
            </a>
            {elapsed && <span className="muted">{elapsed}s</span>}
            <span className="muted">{fmtTime(job.finished_at)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

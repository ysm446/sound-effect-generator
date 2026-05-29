import { useEffect, useState, useCallback } from "react";
import { api } from "./api.js";
import GenerateForm from "./components/GenerateForm.jsx";
import ResultCard from "./components/ResultCard.jsx";

export default function App() {
  const [health, setHealth] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState(null);
  // Sidebar width grows as the prompt gets longer (set by GenerateForm).
  const [formWidth, setFormWidth] = useState(380);
  // A request to load a card's settings back into the form.
  const [copyRequest, setCopyRequest] = useState(null);

  const handleCopyToForm = useCallback((job) => {
    setCopyRequest({
      prompt: job.prompt,
      seconds: job.seconds,
      steps: job.steps,
      cfg_scale: job.cfg_scale,
      seed: job.seed,
      _ts: Date.now(), // ensure the effect re-runs even for identical values
    });
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const list = await api.listJobs();
      setJobs(list);
      setError(null);
    } catch (e) {
      setError("バックエンドに接続できません。サーバーが起動しているか確認してください。");
    }
  }, []);

  // Initial health check + polling loop for live job updates.
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    refreshJobs();
    const t = setInterval(() => {
      refreshJobs();
      api.health().then(setHealth).catch(() => {});
    }, 1500);
    return () => clearInterval(t);
  }, [refreshJobs]);

  const handleSubmit = async (params) => {
    try {
      await api.createJob(params);
      await refreshJobs();
    } catch (e) {
      setError(e.message);
    }
  };

  const handleDelete = async (id) => {
    try {
      await api.deleteJob(id);
      setJobs((prev) => prev.filter((j) => j.id !== id));
    } catch (e) {
      setError(e.message);
    }
  };

  const modelReady = health?.model_ready;
  const queued = jobs.filter((j) => j.status === "queued").length;
  const running = jobs.filter((j) => j.status === "running").length;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Sound Effect Generator</h1>
          <p className="subtitle">Stable Audio 3 Medium · ローカル生成</p>
        </div>
        <div className="status">
          <StatusDot ok={!!health} />
          <span>
            {health
              ? `デバイス: ${health.device ?? "未ロード"} · キュー ${queued} / 実行中 ${running}`
              : "バックエンド停止中"}
          </span>
        </div>
      </header>

      {health && !modelReady && (
        <div className="banner warn">
          ⚠️ モデルファイルが不足しています:{" "}
          {health.missing_files?.join(", ")}
        </div>
      )}
      {error && <div className="banner error">{error}</div>}

      <main
        className="layout"
        style={{ gridTemplateColumns: `${formWidth}px 1fr` }}
      >
        <section className="panel form-panel">
          <h2>生成条件</h2>
          <GenerateForm
            onSubmit={handleSubmit}
            disabled={!modelReady}
            onWidthHint={setFormWidth}
            applyValues={copyRequest}
          />
        </section>

        <section className="panel results-panel">
          <h2>生成結果 ({jobs.length})</h2>
          {jobs.length === 0 ? (
            <p className="empty">まだ生成タスクがありません。左で条件を設定して「生成キューに追加」してください。</p>
          ) : (
            <div className="card-list">
              {jobs.map((job) => (
                <ResultCard
                  key={job.id}
                  job={job}
                  onDelete={handleDelete}
                  onCopyToForm={handleCopyToForm}
                />
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function StatusDot({ ok }) {
  return <span className={`dot ${ok ? "dot-ok" : "dot-bad"}`} />;
}

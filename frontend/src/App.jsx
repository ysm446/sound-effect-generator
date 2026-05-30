import { useEffect, useState, useCallback } from "react";
import { api } from "./api.js";
import GenerateForm from "./components/GenerateForm.jsx";
import ResultCard from "./components/ResultCard.jsx";
import { useI18n, LANGS } from "./i18n.jsx";

export default function App() {
  const { t, lang, setLang } = useI18n();
  const [health, setHealth] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState(null);
  // Sidebar width grows as the prompt gets longer (set by GenerateForm).
  const [formWidth, setFormWidth] = useState(380);
  // A request to load a card's settings back into the form.
  const [copyRequest, setCopyRequest] = useState(null);
  // Available models + current selection.
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState(null);

  const refreshModels = useCallback(async () => {
    try {
      const { models: list, selected } = await api.listModels();
      setModels(list);
      setSelectedModel(selected);
    } catch {
      /* backend down; ignore */
    }
  }, []);

  const handleModelChange = async (key) => {
    try {
      await api.setModel(key);
      setSelectedModel(key);
      await refreshModels();
      api.health().then(setHealth).catch(() => {});
    } catch (e) {
      setError(e.message);
    }
  };

  // Load/unload a resident model from the top-bar toggles. We flip health
  // optimistically so the pill reacts immediately; the next poll reconciles.
  const handleEngineToggle = useCallback(async (name, loaded) => {
    const action = loaded ? "unload" : "load";
    setHealth((h) =>
      h ? { ...h, [`${name}_loading`]: action === "load" } : h
    );
    try {
      await api.setEngine(name, action);
      api.health().then(setHealth).catch(() => {});
    } catch (e) {
      setError(e.message);
    }
  }, []);

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
      // Stored as a key so it follows the current language at render time.
      setError("connectError");
    }
  }, []);

  // Initial health check + polling loop for live job updates.
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    refreshJobs();
    refreshModels();
    const timer = setInterval(() => {
      refreshJobs();
      api.health().then(setHealth).catch(() => {});
    }, 1500);
    return () => clearInterval(timer);
  }, [refreshJobs, refreshModels]);

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

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Sound Effect Generator</h1>
          <p className="subtitle">{t("subtitle")}</p>
        </div>
        <div className="status">
          <select
            className="lang-select"
            value={lang}
            onChange={(e) => setLang(e.target.value)}
            title={t("language")}
          >
            {LANGS.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
          <EngineToggle
            label="LLM"
            loaded={!!health?.llm_loaded}
            loading={!!health?.llm_loading}
            present={health?.llm_present ?? false}
            online={!!health}
            onToggle={() => handleEngineToggle("llm", health?.llm_loaded)}
          />
          <EngineToggle
            label="Stable Audio"
            loaded={!!health?.audio_loaded}
            loading={!!health?.audio_loading}
            present={health?.audio_present ?? false}
            online={!!health}
            onToggle={() => handleEngineToggle("audio", health?.audio_loaded)}
          />
        </div>
      </header>

      {health && !modelReady && (
        <div className="banner warn">
          ⚠️ {t("missingFiles")}{" "}
          {health.missing_files?.join(", ")}
        </div>
      )}
      {error && (
        <div className="banner error">
          {error === "connectError" ? t("connectError") : error}
        </div>
      )}

      <main
        className="layout"
        style={{ gridTemplateColumns: `${formWidth}px 1fr` }}
      >
        <section className="panel form-panel">
          <h2>{t("genSettings")}</h2>
          {models.length > 0 && (
            <label className="model-field">
              {t("model")}
              <select
                className="model-select"
                value={selectedModel ?? ""}
                onChange={(e) => handleModelChange(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                    {m.present ? "" : t("notDownloaded")}
                  </option>
                ))}
              </select>
            </label>
          )}
          <GenerateForm
            onSubmit={handleSubmit}
            disabled={!modelReady}
            onWidthHint={setFormWidth}
            applyValues={copyRequest}
          />
        </section>

        <section className="panel results-panel">
          {jobs.length === 0 ? (
            <p className="empty">{t("empty")}</p>
          ) : (
            <div className="card-list">
              {jobs.map((job) => (
                <ResultCard
                  key={job.id}
                  job={job}
                  modelLabel={
                    models.find((m) => m.key === job.model)?.label || job.model
                  }
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

// A compact on/off pill for a resident model (LLM / Stable Audio). Green dot =
// loaded, grey = off, pulsing amber = loading. Click toggles load/unload.
function EngineToggle({ label, loaded, loading, present, online, onToggle }) {
  const { t } = useI18n();
  const disabled = !online || !present || loading;
  const cls = loading ? "loading" : loaded ? "on" : "off";
  const title = !online
    ? t("backendOffline")
    : !present
    ? t("engineMissing")
    : loading
    ? t("engineLoading")
    : loaded
    ? t("engineUnloadHint")
    : t("engineLoadHint");
  return (
    <button
      type="button"
      className={`engine-toggle ${cls}`}
      onClick={onToggle}
      disabled={disabled}
      title={title}
      aria-pressed={loaded}
    >
      <span className="et-dot" />
      {label}
    </button>
  );
}

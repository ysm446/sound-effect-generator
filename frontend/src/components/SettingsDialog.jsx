import { useEffect, useState, useCallback } from "react";
import { api } from "../api.js";
import { useI18n, LANGS } from "../i18n.jsx";

function CloseIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

function formatSize(bytes) {
  if (!bytes) return "";
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(bytes / 1024 ** 2)} MB`;
}

// App-wide settings (language, LLM model file). Opened from the gear icon in
// the top bar; closes on the X button, the backdrop or Esc.
export default function SettingsDialog({ open, onClose, onLlmChange }) {
  const { t, lang, setLang } = useI18n();
  // {dir, default_dir, is_default_dir, models, selected, present, server_available}
  const [llm, setLlm] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setLlm(await api.getLlm());
      setError(null);
    } catch {
      setLlm(null);
    }
  }, []);

  useEffect(() => {
    if (open) refresh();
  }, [open, refresh]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const applyLlm = async (changes) => {
    try {
      setLlm(await api.setLlm(changes));
      setError(null);
      onLlmChange?.();
    } catch (e) {
      setError(
        e.message?.includes("folder_not_found") ? "llmDirMissing" : e.message
      );
    }
  };

  if (!open) return null;

  const desktop = typeof window !== "undefined" ? window.__DESKTOP__ : null;

  const pickDir = async () => {
    const picked = desktop
      ? await desktop.pickFolder(llm?.dir)
      : window.prompt(t("llmDir"), llm?.dir ?? "");
    if (picked && picked !== llm?.dir) applyLlm({ dir: picked });
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id="settings-title">{t("settings")}</h2>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            title={t("close")}
            aria-label={t("close")}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="modal-body">
          <label className="model-field">
            {t("language")}
            <select
              className="model-select"
              value={lang}
              onChange={(e) => setLang(e.target.value)}
            >
              {LANGS.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>

          <div className="settings-group">
            <div className="settings-title">{t("llmSection")}</div>

            <div className="model-field data-dir-field">
              <span title={t("llmDirHelp")}>{t("llmDir")}</span>
              <input
                className="path-box"
                readOnly
                value={llm?.dir ?? ""}
                title={llm?.dir ?? ""}
              />
              <div className="data-dir-actions">
                <button type="button" className="mini-btn" onClick={pickDir}>
                  {t("browse")}
                </button>
                {desktop && llm && (
                  <button
                    type="button"
                    className="mini-btn"
                    onClick={() => desktop.openPath(llm.dir)}
                  >
                    {t("openFolder")}
                  </button>
                )}
                {llm && !llm.is_default_dir && (
                  <button
                    type="button"
                    className="mini-btn"
                    onClick={() => applyLlm({ dir: "" })}
                    title={llm.default_dir}
                  >
                    {t("useDefault")}
                  </button>
                )}
              </div>
            </div>

            <label className="model-field">
              {t("llmModel")}
              <select
                className="model-select"
                value={llm?.selected ?? ""}
                onChange={(e) => applyLlm({ model: e.target.value })}
                disabled={!llm || llm.models.length === 0}
              >
                {llm && llm.models.length === 0 && (
                  <option value="">{t("llmNone")}</option>
                )}
                {llm?.models.map((m) => (
                  <option key={m.path} value={m.path}>
                    {m.path}
                    {m.size ? ` (${formatSize(m.size)})` : ""}
                  </option>
                ))}
              </select>
            </label>

            {llm && !llm.server_available && (
              <p className="hint">{t("llmNoServer")}</p>
            )}
            {error && (
              <p className="hint">{error === "llmDirMissing" ? t(error) : error}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

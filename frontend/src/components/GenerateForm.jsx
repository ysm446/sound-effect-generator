import { useState, useRef, useEffect } from "react";
import { useI18n } from "../i18n.jsx";
import { api } from "../api.js";

const DEFAULTS = {
  prompt: "",
  seconds: 8,
  steps: 8,
  cfg_scale: 1.0,
  seed: -1,
};

export default function GenerateForm({ onSubmit, disabled, onWidthHint, applyValues }) {
  const { t } = useI18n();
  const [form, setForm] = useState(DEFAULTS);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestion, setSuggestion] = useState(null);
  const taRef = useRef(null);

  // Ask the backend LLM to turn the current (rough) prompt into a polished
  // English sound-effect prompt, shown below as a candidate to apply.
  const handleSuggest = async () => {
    const idea = form.prompt.trim();
    if (!idea || suggesting) return;
    setSuggesting(true);
    setSuggestion(null);
    try {
      const { prompt } = await api.suggest(idea);
      if (prompt) setSuggestion(prompt);
    } catch {
      /* ignore; leave the form untouched */
    } finally {
      setSuggesting(false);
    }
  };

  const applySuggestion = () => {
    setForm((f) => ({ ...f, prompt: suggestion }));
    setSuggestion(null);
  };

  // Load a card's settings into the form (triggered from a result card menu).
  useEffect(() => {
    if (!applyValues) return;
    setForm((f) => ({
      ...f,
      prompt: applyValues.prompt ?? f.prompt,
      seconds: applyValues.seconds ?? f.seconds,
      steps: applyValues.steps ?? f.steps,
      cfg_scale: applyValues.cfg_scale ?? f.cfg_scale,
      seed: applyValues.seed ?? f.seed,
    }));
  }, [applyValues]);

  // Auto-grow the prompt box to fit its content, and ask the parent to widen
  // the sidebar as the number of (wrapped) lines increases.
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
    const rows = Math.round(ta.scrollHeight / 22);
    const width = Math.min(560, Math.max(380, 380 + (rows - 3) * 26));
    onWidthHint?.(width);
  }, [form.prompt, onWidthHint]);

  const update = (key) => (e) => {
    const value =
      e.target.type === "number" || e.target.type === "range"
        ? Number(e.target.value)
        : e.target.value;
    setForm((f) => ({ ...f, [key]: value }));
  };

  const submit = (e) => {
    e.preventDefault();
    if (!form.prompt.trim()) return;
    onSubmit({
      prompt: form.prompt.trim(),
      seconds: form.seconds,
      steps: form.steps,
      cfg_scale: form.cfg_scale,
      seed: form.seed,
    });
  };

  return (
    <form onSubmit={submit} className="gen-form">
      <label>
        <span className="label-row">
          {t("prompt")}
          <button
            type="button"
            className="suggest-btn"
            onClick={handleSuggest}
            disabled={!form.prompt.trim() || suggesting}
          >
            {suggesting ? t("suggesting") : `✨ ${t("suggest")}`}
          </button>
        </span>
        <textarea
          ref={taRef}
          rows={3}
          value={form.prompt}
          onChange={update("prompt")}
          placeholder="e.g. Heavy wooden door creaking open slowly"
          required
        />
      </label>

      {suggestion && (
        <button
          type="button"
          className="suggestion-chip"
          onClick={applySuggestion}
          title={t("suggestHint")}
        >
          {suggestion}
        </button>
      )}

      <div className="settings-group">
        <SliderField
          label={t("length")}
          help={t("lengthHelp")}
          display={`${form.seconds}s`}
          min={1}
          max={30}
          step={1}
          value={form.seconds}
          onChange={update("seconds")}
        />
        <SliderField
          label={t("steps")}
          help={t("stepsHelp")}
          display={form.steps}
          min={4}
          max={50}
          step={1}
          value={form.steps}
          onChange={update("steps")}
        />
        <SliderField
          label={t("cfg")}
          help={t("cfgHelp")}
          display={form.cfg_scale.toFixed(1)}
          min={0}
          max={10}
          step={0.5}
          value={form.cfg_scale}
          onChange={update("cfg_scale")}
        />

        <div className="slider-field">
          <div className="slider-head">
            <span className="slider-label" data-help={t("seedHelp")}>
              {t("seed")}
            </span>
            <div className="seed-control">
              <button
                type="button"
                className="dice-btn"
                title={t("random")}
                onClick={() => setForm((f) => ({ ...f, seed: -1 }))}
              >
                <DiceIcon />
              </button>
              <input
                type="number"
                className="slider-value-input"
                value={form.seed}
                onChange={update("seed")}
              />
            </div>
          </div>
        </div>
      </div>

      <button type="submit" className="primary" disabled={disabled}>
        {t("addToQueue")}
      </button>
      {disabled && (
        <p className="hint">{t("notReady")}</p>
      )}
    </form>
  );
}

const DiceIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="3" width="18" height="18" rx="4" />
    <circle cx="8" cy="8" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="16" cy="8" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="8" cy="16" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="16" cy="16" r="1.3" fill="currentColor" stroke="none" />
  </svg>
);

// Label on the left, boxed value on the right, slider below.
function SliderField({ label, help, display, value, ...inputProps }) {
  return (
    <div className="slider-field">
      <div className="slider-head">
        <span className="slider-label" data-help={help}>
          {label}
        </span>
        <span className="slider-value">{display ?? value}</span>
      </div>
      <input type="range" value={value} {...inputProps} />
    </div>
  );
}

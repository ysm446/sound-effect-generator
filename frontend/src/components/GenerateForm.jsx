import { useState, useRef, useEffect } from "react";

const DEFAULTS = {
  prompt: "",
  seconds: 8,
  steps: 8,
  cfg_scale: 1.0,
  seed: -1,
};

// A few quick-start prompt ideas for sound effects.
const PRESETS = [
  "Heavy wooden door creaking open slowly",
  "Sci-fi laser gun shot with reverb",
  "Footsteps on gravel, walking pace",
  "Glass shattering on a tile floor",
  "Retro 8-bit coin pickup jingle",
  "Thunder rumble with distant rain",
];

export default function GenerateForm({ onSubmit, disabled, onWidthHint, applyValues }) {
  const [form, setForm] = useState(DEFAULTS);
  const taRef = useRef(null);

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
        プロンプト（英語推奨）
        <textarea
          ref={taRef}
          rows={3}
          value={form.prompt}
          onChange={update("prompt")}
          placeholder="e.g. Heavy wooden door creaking open slowly"
          required
        />
      </label>

      <div className="presets">
        {PRESETS.map((p) => (
          <button
            type="button"
            key={p}
            className="chip"
            onClick={() => setForm((f) => ({ ...f, prompt: p }))}
          >
            {p}
          </button>
        ))}
      </div>

      <div className="settings-group">
        <SliderField
          label="長さ"
          help="生成する音の長さ（秒）"
          display={`${form.seconds}s`}
          min={1}
          max={30}
          step={1}
          value={form.seconds}
          onChange={update("seconds")}
        />
        <SliderField
          label="ステップ数"
          help="拡散のステップ数。多いほど高品質だが遅くなる（標準: 8）"
          display={form.steps}
          min={4}
          max={50}
          step={1}
          value={form.steps}
          onChange={update("steps")}
        />
        <SliderField
          label="CFG"
          help="プロンプトへの忠実度。高いほど指示に厳密になる（標準: 1.0）"
          display={form.cfg_scale.toFixed(1)}
          min={0}
          max={10}
          step={0.5}
          value={form.cfg_scale}
          onChange={update("cfg_scale")}
        />

        <div className="slider-field">
          <div className="slider-head">
            <span className="slider-label" data-help="乱数シード。同じ値なら同じ音を再現できる。-1 でランダム">
              シード (-1=ランダム)
            </span>
            <div className="seed-control">
              <button
                type="button"
                className="dice-btn"
                title="ランダム (-1)"
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
        ＋ 生成キューに追加
      </button>
      {disabled && (
        <p className="hint">モデル未準備のため生成できません。</p>
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

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

export default function GenerateForm({ onSubmit, disabled, onWidthHint }) {
  const [form, setForm] = useState(DEFAULTS);
  const taRef = useRef(null);

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

      <SliderField
        label="長さ"
        display={`${form.seconds}s`}
        min={1}
        max={30}
        step={1}
        value={form.seconds}
        onChange={update("seconds")}
      />
      <SliderField
        label="ステップ数"
        display={form.steps}
        min={4}
        max={50}
        step={1}
        value={form.steps}
        onChange={update("steps")}
      />
      <SliderField
        label="CFG"
        display={form.cfg_scale.toFixed(1)}
        min={0}
        max={10}
        step={0.5}
        value={form.cfg_scale}
        onChange={update("cfg_scale")}
      />

      <div className="slider-field">
        <div className="slider-head">
          <span className="slider-label">シード (-1=ランダム)</span>
          <input
            type="number"
            className="slider-value-input"
            value={form.seed}
            onChange={update("seed")}
          />
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

// Label on the left, boxed value on the right, slider below.
function SliderField({ label, display, value, ...inputProps }) {
  return (
    <div className="slider-field">
      <div className="slider-head">
        <span className="slider-label">{label}</span>
        <span className="slider-value">{display ?? value}</span>
      </div>
      <input type="range" value={value} {...inputProps} />
    </div>
  );
}

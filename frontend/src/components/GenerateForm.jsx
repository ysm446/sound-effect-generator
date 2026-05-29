import { useState } from "react";

const DEFAULTS = {
  prompt: "",
  negative_prompt: "",
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

export default function GenerateForm({ onSubmit, disabled }) {
  const [form, setForm] = useState(DEFAULTS);

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
      negative_prompt: form.negative_prompt.trim() || null,
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

      <label>
        ネガティブプロンプト（任意）
        <input
          type="text"
          value={form.negative_prompt}
          onChange={update("negative_prompt")}
          placeholder="e.g. music, voice"
        />
      </label>

      <div className="row">
        <label>
          長さ: {form.seconds}s
          <input
            type="range"
            min={1}
            max={30}
            step={1}
            value={form.seconds}
            onChange={update("seconds")}
          />
        </label>
        <label>
          ステップ数: {form.steps}
          <input
            type="range"
            min={4}
            max={50}
            step={1}
            value={form.steps}
            onChange={update("steps")}
          />
        </label>
      </div>

      <div className="row">
        <label>
          CFG: {form.cfg_scale.toFixed(1)}
          <input
            type="range"
            min={0}
            max={10}
            step={0.5}
            value={form.cfg_scale}
            onChange={update("cfg_scale")}
          />
        </label>
        <label>
          シード (-1=ランダム)
          <input
            type="number"
            value={form.seed}
            onChange={update("seed")}
          />
        </label>
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

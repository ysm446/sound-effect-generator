import { createContext, useContext, useState, useEffect } from "react";

// Selectable UI languages. Backend-originated text (generation progress,
// error messages from the server) is left as-is.
export const LANGS = [
  { code: "en", label: "English" },
  { code: "ja", label: "日本語" },
];

const STRINGS = {
  en: {
    subtitle: "Stable Audio 3 · Local generation",
    language: "Language",
    model: "Model",
    notDownloaded: " (not downloaded)",
    device: "Device",
    notLoaded: "not loaded",
    backendOffline: "Backend offline",
    engineLoadHint: "Off — click to load into memory",
    engineUnloadHint: "Loaded — click to unload",
    engineLoading: "Loading…",
    engineMissing: "Model files not available",
    missingFiles: "Missing model files:",
    genSettings: "Generation settings",
    empty: 'No generations yet. Set the options on the left and click "Add to queue".',
    connectError: "Cannot connect to the backend. Check that the server is running.",

    prompt: "Prompt (English recommended)",
    suggest: "Suggest",
    suggesting: "Thinking…",
    suggestHint: "Click to use this prompt",
    length: "Length",
    lengthHelp: "Length of the generated sound (seconds)",
    steps: "Steps",
    stepsHelp: "Number of diffusion steps. More steps = higher quality but slower (default: 8)",
    cfg: "CFG",
    cfgHelp: "How closely the output follows the prompt. Higher is stricter (default: 1.0)",
    seed: "Seed (-1 = random)",
    seedHelp: "Random seed. The same value reproduces the same sound. -1 for random",
    random: "Random (-1)",
    addToQueue: "+ Add to queue",
    notReady: "Model not ready, generation unavailable.",

    statusQueued: "Queued",
    statusRunning: "Generating",
    statusDone: "Done",
    statusError: "Error",
    menu: "Menu",
    copyToForm: "Copy to form",
    download: "Download",
    delete: "Delete",

    play: "Play",
    pause: "Pause",
    seek: "Click / drag to seek",
    mute: "Mute",
    unmute: "Unmute",
    volume: "Volume",
    loop: "Loop",
  },
  ja: {
    subtitle: "Stable Audio 3 · ローカル生成",
    language: "言語",
    model: "モデル",
    notDownloaded: "（未DL）",
    device: "デバイス",
    notLoaded: "未ロード",
    backendOffline: "バックエンド停止中",
    engineLoadHint: "オフ — クリックでメモリに読み込み",
    engineUnloadHint: "読み込み済み — クリックで解放",
    engineLoading: "読み込み中…",
    engineMissing: "モデルファイルがありません",
    missingFiles: "モデルファイルが不足しています:",
    genSettings: "生成条件",
    empty: "まだ生成タスクがありません。左で条件を設定して「生成キューに追加」してください。",
    connectError: "バックエンドに接続できません。サーバーが起動しているか確認してください。",

    prompt: "プロンプト（英語推奨）",
    suggest: "推測",
    suggesting: "推測中…",
    suggestHint: "クリックで適用",
    length: "長さ",
    lengthHelp: "生成する音の長さ（秒）",
    steps: "ステップ数",
    stepsHelp: "拡散のステップ数。多いほど高品質だが遅くなる（標準: 8）",
    cfg: "CFG",
    cfgHelp: "プロンプトへの忠実度。高いほど指示に厳密になる（標準: 1.0）",
    seed: "シード (-1=ランダム)",
    seedHelp: "乱数シード。同じ値なら同じ音を再現できる。-1 でランダム",
    random: "ランダム (-1)",
    addToQueue: "＋ 生成キューに追加",
    notReady: "モデル未準備のため生成できません。",

    statusQueued: "待機中",
    statusRunning: "生成中",
    statusDone: "完了",
    statusError: "エラー",
    menu: "メニュー",
    copyToForm: "フォームにコピー",
    download: "ダウンロード",
    delete: "削除",

    play: "再生",
    pause: "一時停止",
    seek: "クリック/ドラッグでシーク",
    mute: "ミュート",
    unmute: "ミュート解除",
    volume: "音量",
    loop: "ループ再生",
  },
};

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => {
    const saved = localStorage.getItem("lang");
    return STRINGS[saved] ? saved : "en";
  });

  useEffect(() => {
    localStorage.setItem("lang", lang);
    document.documentElement.lang = lang;
  }, [lang]);

  // Look up a key in the current language, falling back to English, then the
  // key itself (so a missing translation is visible rather than blank).
  const t = (key) => STRINGS[lang]?.[key] ?? STRINGS.en[key] ?? key;

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}

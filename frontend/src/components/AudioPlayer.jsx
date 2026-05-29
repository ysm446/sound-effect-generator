import { useRef, useState, useEffect, useCallback } from "react";

function fmt(t) {
  if (!isFinite(t) || t < 0) return "0:00";
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

// One shared AudioContext, created lazily, just for decoding waveforms.
let _ctx = null;
function audioCtx() {
  if (!_ctx) _ctx = new (window.AudioContext || window.webkitAudioContext)();
  return _ctx;
}

const BARS = 130;

const PlayIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
    <path d="M8 5v14l11-7z" />
  </svg>
);
const PauseIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
    <rect x="6" y="5" width="4" height="14" rx="1" />
    <rect x="14" y="5" width="4" height="14" rx="1" />
  </svg>
);
const VolIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
    <path d="M4 9v6h4l5 4V5L8 9H4z" />
    <path d="M16 8.5a3.5 3.5 0 0 1 0 7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);
const MuteIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
    <path d="M4 9v6h4l5 4V5L8 9H4z" />
    <path d="M16 9l5 6M21 9l-5 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

export default function AudioPlayer({ src }) {
  const audioRef = useRef(null);
  const canvasRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [vol, setVol] = useState(1);
  const [muted, setMuted] = useState(false);
  const [peaks, setPeaks] = useState(null);

  // Decode the audio file once and reduce it to per-bar peak amplitudes.
  useEffect(() => {
    let cancelled = false;
    setPeaks(null);
    fetch(src)
      .then((r) => r.arrayBuffer())
      .then((buf) => audioCtx().decodeAudioData(buf))
      .then((audioBuf) => {
        if (cancelled) return;
        const data = audioBuf.getChannelData(0);
        const block = Math.max(1, Math.floor(data.length / BARS));
        const pk = new Float32Array(BARS);
        let norm = 0;
        for (let i = 0; i < BARS; i++) {
          let max = 0;
          const start = i * block;
          for (let j = 0; j < block; j++) {
            const v = Math.abs(data[start + j] || 0);
            if (v > max) max = v;
          }
          pk[i] = max;
          if (max > norm) norm = max;
        }
        if (norm > 0) for (let i = 0; i < BARS; i++) pk[i] /= norm;
        setPeaks(pk);
      })
      .catch(() => setPeaks(null));
    return () => {
      cancelled = true;
    };
  }, [src]);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    const onTime = () => setCur(a.currentTime);
    const onMeta = () => setDur(a.duration);
    const onEnd = () => {
      setPlaying(false);
      setCur(0);
    };
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("loadedmetadata", onMeta);
    a.addEventListener("ended", onEnd);
    return () => {
      a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("loadedmetadata", onMeta);
      a.removeEventListener("ended", onEnd);
    };
  }, []);

  // Draw the waveform, colouring the played portion.
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const css = getComputedStyle(document.documentElement);
    const played = (css.getPropertyValue("--accent") || "#6c8cff").trim();
    const unplayed = "#4b5360";

    const n = peaks ? peaks.length : BARS;
    const gap = 1.5;
    const barW = Math.max(1, (w - gap * (n - 1)) / n);
    const progress = dur ? cur / dur : 0;
    for (let i = 0; i < n; i++) {
      const amp = peaks ? peaks[i] : 0.06;
      const bh = Math.max(2, amp * (h - 2));
      const x = i * (barW + gap);
      const y = (h - bh) / 2;
      ctx.fillStyle = i / n < progress ? played : unplayed;
      ctx.fillRect(x, y, barW, bh);
    }
  }, [peaks, cur, dur]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    const onResize = () => draw();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [draw]);

  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) {
      a.play();
      setPlaying(true);
    } else {
      a.pause();
      setPlaying(false);
    }
  };

  const seekFromEvent = (clientX) => {
    const canvas = canvasRef.current;
    const a = audioRef.current;
    if (!canvas || !a || !dur) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    a.currentTime = ratio * dur;
    setCur(ratio * dur);
  };

  const onCanvasDown = (e) => {
    seekFromEvent(e.clientX);
    const onMove = (ev) => seekFromEvent(ev.clientX);
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const toggleMute = () => {
    const a = audioRef.current;
    if (!a) return;
    a.muted = !a.muted;
    setMuted(a.muted);
  };

  const changeVol = (e) => {
    const v = Number(e.target.value);
    const a = audioRef.current;
    setVol(v);
    if (a) {
      a.volume = v;
      a.muted = v === 0;
    }
    setMuted(v === 0);
  };

  // Keep the <audio> element's volume in sync (e.g. on mount / src change).
  useEffect(() => {
    const a = audioRef.current;
    if (a) a.volume = vol;
  }, [vol, src]);

  return (
    <div className="audio-player">
      <audio ref={audioRef} src={src} preload="metadata" />

      <button className="ap-play" onClick={toggle} title={playing ? "一時停止" : "再生"}>
        {playing ? <PauseIcon /> : <PlayIcon />}
      </button>

      <span className="ap-time">
        {fmt(cur)} / {fmt(dur)}
      </span>

      <canvas
        ref={canvasRef}
        className="ap-wave"
        onMouseDown={onCanvasDown}
        title="クリック/ドラッグでシーク"
      />

      <div className="ap-volgroup">
        <button className="ap-vol" onClick={toggleMute} title={muted ? "ミュート解除" : "ミュート"}>
          {muted || vol === 0 ? <MuteIcon /> : <VolIcon />}
        </button>
        <input
          className="ap-volslider"
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={muted ? 0 : vol}
          onChange={changeVol}
          title="音量"
        />
      </div>
    </div>
  );
}

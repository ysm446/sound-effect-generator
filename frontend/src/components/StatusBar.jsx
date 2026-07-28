import { useEffect, useState } from "react";

// Bottom status bar showing system resources (CPU / RAM / GPU / VRAM),
// pushed from the Electron main process once a second. Renders nothing in a
// plain browser (no __DESKTOP__ bridge) or until the first sample arrives.

function fmtBytes(bytes) {
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1024 ** 2).toFixed(0)} MB`;
}

function fmtMb(mb) {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
}

function ResourceBar({ label, pct, detail }) {
  const clamped = Math.min(100, Math.max(0, pct));
  const color =
    clamped > 85 ? "var(--err)" : clamped > 65 ? "var(--warn)" : "var(--accent)";
  return (
    <div className="resource">
      <span className="resource-label">{label}</span>
      <div className="resource-track">
        <div
          className="resource-fill"
          style={{ width: `${clamped}%`, backgroundColor: color }}
        />
      </div>
      <span className="resource-detail">{detail}</span>
    </div>
  );
}

export default function StatusBar() {
  const [res, setRes] = useState(null);

  useEffect(() => {
    const desktop = typeof window !== "undefined" ? window.__DESKTOP__ : null;
    if (!desktop?.onSystemResources) return;
    return desktop.onSystemResources(setRes);
  }, []);

  if (!res) return null;

  const hasGpu = res.gpuUsage !== null;
  const hasVram = res.vramUsed !== null && res.vramTotal !== null;

  return (
    <footer className="statusbar">
      <ResourceBar label="CPU" pct={res.cpuUsage} detail={`${res.cpuUsage}%`} />
      <ResourceBar
        label="RAM"
        pct={(res.ramUsed / res.ramTotal) * 100}
        detail={`${fmtBytes(res.ramUsed)} / ${fmtBytes(res.ramTotal)}`}
      />
      {hasGpu && (
        <ResourceBar label="GPU" pct={res.gpuUsage} detail={`${res.gpuUsage}%`} />
      )}
      {hasVram && (
        <ResourceBar
          label="VRAM"
          pct={(res.vramUsed / res.vramTotal) * 100}
          detail={`${fmtMb(res.vramUsed)} / ${fmtMb(res.vramTotal)}`}
        />
      )}
    </footer>
  );
}

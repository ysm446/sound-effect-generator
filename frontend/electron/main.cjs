const { app, BrowserWindow, Menu, shell, dialog, ipcMain } = require("electron");
const { spawn, exec } = require("node:child_process");
const path = require("node:path");
const http = require("node:http");
const fs = require("node:fs");
const os = require("node:os");

const isDev = process.env.NODE_ENV === "development";
const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = 8765;

// Project-embedded Python interpreter (created via .venv).
const PYTHON_EXE = path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe");
const SERVER_SCRIPT = path.join(PROJECT_ROOT, "backend", "server.py");

let pyProc = null;
let win = null;

function startBackend() {
  pyProc = spawn(
    PYTHON_EXE,
    [SERVER_SCRIPT, "--host", BACKEND_HOST, "--port", String(BACKEND_PORT)],
    {
      cwd: path.join(PROJECT_ROOT, "backend"),
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    }
  );
  pyProc.stdout.on("data", (d) => process.stdout.write(`[py] ${d}`));
  pyProc.stderr.on("data", (d) => process.stderr.write(`[py] ${d}`));
  pyProc.on("exit", (code) => {
    console.log(`[py] backend exited with code ${code}`);
    pyProc = null;
  });
}

function waitForBackend(timeoutMs = 60000) {
  const url = `http://${BACKEND_HOST}:${BACKEND_PORT}/api/health`;
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() - start > timeoutMs) {
          reject(new Error("backend did not start in time"));
        } else {
          setTimeout(tick, 500);
        }
      });
    };
    tick();
  });
}

async function createWindow() {
  win = new BrowserWindow({
    width: 1600,
    height: 900,
    // width/height refer to the web content area, excluding the title bar/frame.
    useContentSize: true,
    backgroundColor: "#0f1115",
    title: "Sound Effect Generator",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Open external links in the system browser, not inside the app window.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // F12: capture the web content area (excludes the OS title bar/frame) and
  // save it as a PNG under data/screenshot/. Handled in the main process so it
  // works regardless of the renderer's focus/state.
  win.webContents.on("before-input-event", (event, input) => {
    if (input.type === "keyDown" && input.key === "F12") {
      event.preventDefault();
      captureScreenshot();
    }
  });

  if (isDev) {
    await win.loadURL("http://localhost:5173");
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    await win.loadFile(path.join(PROJECT_ROOT, "frontend", "dist", "index.html"));
  }
}

// Ask the backend where the data folder currently is (it is user-configurable);
// null if the backend is unreachable.
function fetchDataDir() {
  const url = `http://${BACKEND_HOST}:${BACKEND_PORT}/api/datadir`;
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (body += c));
      res.on("end", () => {
        try {
          resolve(JSON.parse(body).path || null);
        } catch {
          resolve(null);
        }
      });
    });
    req.on("error", () => resolve(null));
  });
}

// Capture the current window content and write it to <data dir>/screenshot/ as
// a timestamped PNG. Errors are logged but never surfaced to the user.
async function captureScreenshot() {
  if (!win) return;
  try {
    const image = await win.webContents.capturePage();
    const base = (await fetchDataDir()) || path.join(PROJECT_ROOT, "data");
    const dir = path.join(base, "screenshot");
    fs.mkdirSync(dir, { recursive: true });
    // Filesystem-safe timestamp: 2026-07-24T12-34-56-789Z
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    const file = path.join(dir, `screenshot-${ts}.png`);
    fs.writeFileSync(file, image.toPNG());
    console.log(`[screenshot] saved ${file}`);
  } catch (e) {
    console.error(`[screenshot] failed: ${e.message}`);
  }
}

// ---------------------------------------------------------------------------
// System resource monitor: CPU/RAM via node:os, GPU/VRAM via nvidia-smi.
// Pushed to the renderer once a second over IPC — no HTTP, no extra
// dependencies, and it keeps working even if the Python backend is down.
// ---------------------------------------------------------------------------

function sampleCpus() {
  return os.cpus().map((cpu) => {
    const times = cpu.times;
    const total = Object.values(times).reduce((a, b) => a + b, 0);
    return { idle: times.idle, total };
  });
}

// os.cpus() reports cumulative times, so usage must come from the delta
// between two samples.
function computeCpuUsage(prev, curr) {
  let totalDelta = 0;
  let idleDelta = 0;
  for (let i = 0; i < prev.length && i < curr.length; i++) {
    totalDelta += curr[i].total - prev[i].total;
    idleDelta += curr[i].idle - prev[i].idle;
  }
  return totalDelta === 0 ? 0 : (1 - idleDelta / totalDelta) * 100;
}

let cpuSample = sampleCpus();
let cachedGpu = { gpuUsage: null, vramUsed: null, vramTotal: null };
// null = unknown yet; false = nvidia-smi missing/broken, never query again.
let nvidiaSmiAvailable = null;
let gpuQueryInFlight = false;
let resourcesInterval = null;

function queryNvidiaSmi() {
  return new Promise((resolve) => {
    const empty = { gpuUsage: null, vramUsed: null, vramTotal: null };
    const timeout = setTimeout(() => resolve(empty), 3000);
    exec(
      "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits",
      { windowsHide: true },
      (err, stdout) => {
        clearTimeout(timeout);
        if (err || !stdout) {
          nvidiaSmiAvailable = false;
          resolve(empty);
          return;
        }
        const parts = stdout.trim().split("\n")[0].split(",").map((s) => parseFloat(s.trim()));
        if (parts.length >= 3 && parts.every((n) => !isNaN(n))) {
          nvidiaSmiAvailable = true;
          resolve({ gpuUsage: parts[0], vramUsed: parts[1], vramTotal: parts[2] });
        } else {
          nvidiaSmiAvailable = false;
          resolve(empty);
        }
      }
    );
  });
}

function startResourceMonitor() {
  const refreshGpu = () => {
    if (gpuQueryInFlight || nvidiaSmiAvailable === false) return;
    gpuQueryInFlight = true;
    queryNvidiaSmi().then((info) => {
      cachedGpu = info;
      gpuQueryInFlight = false;
    });
  };
  refreshGpu();

  resourcesInterval = setInterval(() => {
    const prevSample = cpuSample;
    const currSample = sampleCpus();
    cpuSample = currSample;

    const totalMem = os.totalmem();
    const payload = {
      cpuUsage: Math.round(computeCpuUsage(prevSample, currSample)),
      ramUsed: totalMem - os.freemem(), // bytes
      ramTotal: totalMem, // bytes
      gpuUsage: cachedGpu.gpuUsage !== null ? Math.round(cachedGpu.gpuUsage) : null,
      vramUsed: cachedGpu.vramUsed, // MiB
      vramTotal: cachedGpu.vramTotal, // MiB
    };
    refreshGpu();

    for (const w of BrowserWindow.getAllWindows()) {
      if (!w.isDestroyed() && !w.webContents.isDestroyed()) {
        w.webContents.send("system:resources", payload);
      }
    }
  }, 1000);
}

// The renderer talks to the backend over HTTP, but a native folder picker and
// "reveal in explorer" can only come from the main process, so these two go
// through IPC (see preload.cjs).
function registerIpc() {
  ipcMain.handle("dialog:pick-folder", async (_e, defaultPath) => {
    const { canceled, filePaths } = await dialog.showOpenDialog(win, {
      properties: ["openDirectory", "createDirectory"],
      defaultPath: defaultPath || undefined,
    });
    return canceled || filePaths.length === 0 ? null : filePaths[0];
  });

  ipcMain.handle("shell:open-path", async (_e, target) => {
    if (!target) return false;
    const err = await shell.openPath(target);
    if (err) console.error(`[shell] openPath failed: ${err}`);
    return !err;
  });
}

app.whenReady().then(async () => {
  // Remove the default application menu (File / Edit / View ...).
  Menu.setApplicationMenu(null);

  registerIpc();
  startResourceMonitor();

  startBackend();
  try {
    await waitForBackend();
  } catch (e) {
    console.error(e.message);
  }
  await createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

function shutdown() {
  if (resourcesInterval) {
    clearInterval(resourcesInterval);
    resourcesInterval = null;
  }
  if (pyProc) {
    pyProc.kill();
    pyProc = null;
  }
}

app.on("window-all-closed", () => {
  shutdown();
  if (process.platform !== "darwin") app.quit();
});
app.on("before-quit", shutdown);
process.on("exit", shutdown);

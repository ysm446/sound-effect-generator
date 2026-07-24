const { app, BrowserWindow, Menu, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const http = require("node:http");
const fs = require("node:fs");

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

// Capture the current window content and write it to data/screenshot/ as a
// timestamped PNG. Errors are logged but never surfaced to the user.
async function captureScreenshot() {
  if (!win) return;
  try {
    const image = await win.webContents.capturePage();
    const dir = path.join(PROJECT_ROOT, "data", "screenshot");
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

app.whenReady().then(async () => {
  // Remove the default application menu (File / Edit / View ...).
  Menu.setApplicationMenu(null);

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

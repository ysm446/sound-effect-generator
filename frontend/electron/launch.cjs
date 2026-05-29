// Launches Electron with a clean environment.
//
// VS Code's integrated terminal (and other Electron-based parents) export
// ELECTRON_RUN_AS_NODE=1, which makes a spawned `electron` run as plain Node —
// then `require("electron")` returns a path string and `app` is undefined.
// We strip that variable here and spawn the real Electron runtime.
const { spawn } = require("node:child_process");

// In a plain Node process, requiring "electron" yields the path to the binary.
const electronPath = require("electron");

const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;

const child = spawn(electronPath, ["."], { stdio: "inherit", env });
child.on("close", (code) => process.exit(code ?? 0));

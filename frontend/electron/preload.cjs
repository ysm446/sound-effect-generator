const { contextBridge, ipcRenderer } = require("electron");

// Expose the backend base URL to the renderer. The renderer talks to the
// FastAPI server directly over HTTP (CORS is open on localhost), so no IPC
// bridge is required for the API itself.
contextBridge.exposeInMainWorld("__API_BASE__", "http://127.0.0.1:8765");

// Desktop-only helpers that HTTP can't provide: the native folder picker and
// opening a folder in Explorer. Absent when running in a plain browser, so the
// UI must degrade gracefully (manual path entry).
contextBridge.exposeInMainWorld("__DESKTOP__", {
  pickFolder: (defaultPath) => ipcRenderer.invoke("dialog:pick-folder", defaultPath),
  openPath: (target) => ipcRenderer.invoke("shell:open-path", target),
  // System resources pushed from the main process once a second.
  // Returns an unsubscribe function (usable directly as a useEffect cleanup).
  onSystemResources: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("system:resources", listener);
    return () => ipcRenderer.off("system:resources", listener);
  },
});

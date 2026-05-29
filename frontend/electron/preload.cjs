const { contextBridge } = require("electron");

// Expose the backend base URL to the renderer. The renderer talks to the
// FastAPI server directly over HTTP (CORS is open on localhost), so no IPC
// bridge is required for the API itself.
contextBridge.exposeInMainWorld("__API_BASE__", "http://127.0.0.1:8765");

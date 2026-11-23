import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import express from "express";
import { createServer as createViteServer } from "vite";

const execFileAsync = promisify(execFile);
const ROOT = process.cwd();
const PORT = 3000;

async function runPythonInspector(args: string[]): Promise<unknown> {
  const { stdout } = await execFileAsync("python3", ["scripts/inspect_phase1.py", ...args], {
    cwd: ROOT,
    maxBuffer: 10 * 1024 * 1024,
  });
  return JSON.parse(stdout);
}

async function runPythonPhase2(args: string[]): Promise<unknown> {
  const { stdout } = await execFileAsync("python3", ["scripts/inspect_phase2.py", ...args], {
    cwd: ROOT,
    maxBuffer: 10 * 1024 * 1024,
  });
  return JSON.parse(stdout);
}

async function runPythonPhase3(args: string[]): Promise<unknown> {
  const { stdout } = await execFileAsync("python3", ["scripts/inspect_phase3.py", ...args], {
    cwd: ROOT,
    maxBuffer: 10 * 1024 * 1024,
  });
  return JSON.parse(stdout);
}

async function runPythonPhase4(args: string[]): Promise<unknown> {
  const { stdout } = await execFileAsync("python3", ["scripts/inspect_phase4.py", ...args], {
    cwd: ROOT,
    maxBuffer: 10 * 1024 * 1024,
  });
  return JSON.parse(stdout);
}

async function runPythonPhase5(args: string[]): Promise<unknown> {
  const { stdout } = await execFileAsync("python3", ["scripts/inspect_phase5.py", ...args], {
    cwd: ROOT,
    maxBuffer: 10 * 1024 * 1024,
  });
  return JSON.parse(stdout);
}

async function runPythonPhase6(args: string[]): Promise<unknown> {
  const { stdout } = await execFileAsync("python3", ["scripts/inspect_phase6.py", ...args], {
    cwd: ROOT,
    maxBuffer: 10 * 1024 * 1024,
  });
  return JSON.parse(stdout);
}

async function runPythonPhase7(args: string[]): Promise<unknown> {
  const { stdout } = await execFileAsync("python3", ["scripts/inspect_phase7.py", ...args], {
    cwd: ROOT,
    maxBuffer: 10 * 1024 * 1024,
  });
  return JSON.parse(stdout);
}

async function startServer() {
  const app = express();
  app.use(express.json());

  app.get("/api/phase1/overview", async (_req, res) => {
    try {
      const data = await runPythonInspector(["overview"]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to load Phase 1 overview" });
    }
  });

  app.get("/api/phase2/overview", async (_req, res) => {
    try {
      const data = await runPythonPhase2(["overview"]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to load Phase 2 overview" });
    }
  });

  app.get("/api/phase3/overview", async (_req, res) => {
    try {
      const data = await runPythonPhase3(["overview"]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to load Phase 3 overview" });
    }
  });

  app.get("/api/phase4/overview", async (_req, res) => {
    try {
      const data = await runPythonPhase4(["overview"]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to load Phase 4 overview" });
    }
  });

  app.post("/api/phase4/search", async (req, res) => {
    try {
      const query = String(req.body?.query || "").trim();
      if (!query) {
        res.status(400).json({ error: "Query is required" });
        return;
      }
      const data = await runPythonPhase4(["search", JSON.stringify(req.body || {})]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to search documents" });
    }
  });

  app.get("/api/phase5/overview", async (_req, res) => {
    try {
      const data = await runPythonPhase5(["overview"]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to load Phase 5 overview" });
    }
  });

  app.post("/api/phase5/route", async (req, res) => {
    try {
      const query = String(req.body?.query || "").trim();
      if (!query) {
        res.status(400).json({ error: "Query is required" });
        return;
      }
      const data = await runPythonPhase5(["route", JSON.stringify(req.body || {})]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to route query" });
    }
  });

  app.get("/api/phase6/overview", async (_req, res) => {
    try {
      const data = await runPythonPhase6(["overview"]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to load Phase 6 overview" });
    }
  });

  app.post("/api/phase6/synthesize", async (req, res) => {
    try {
      const query = String(req.body?.query || "").trim();
      if (!query) {
        res.status(400).json({ error: "Query is required" });
        return;
      }
      const data = await runPythonPhase6(["synthesize", JSON.stringify(req.body || {})]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to synthesize response" });
    }
  });

  app.get("/api/phase7/overview", async (_req, res) => {
    try {
      const data = await runPythonPhase7(["overview"]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to load Phase 7 overview" });
    }
  });

  app.post("/api/phase7/chat", async (req, res) => {
    try {
      const query = String(req.body?.query || "").trim();
      if (!query) {
        res.status(400).json({ error: "Query is required" });
        return;
      }
      const data = await runPythonPhase7(["chat", JSON.stringify(req.body || {})]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to process assistant chat turn" });
    }
  });

  app.post("/api/phase7/mcp", async (req, res) => {
    try {
      const data = await runPythonPhase7(["mcp", JSON.stringify(req.body || {})]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to execute MCP tool call" });
    }
  });

  app.post("/api/phase7/eval", async (_req, res) => {
    try {
      const data = await runPythonPhase7(["eval"]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to run gold evaluation" });
    }
  });

  app.post("/api/phase3/execute", async (req, res) => {
    try {
      const sql = String(req.body?.sql || "").trim();
      if (!sql) {
        res.status(400).json({ error: "SQL statement is required" });
        return;
      }
      const data = await runPythonPhase3(["execute", sql]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to execute SQL" });
    }
  });

  app.post("/api/phase2/retrieve-tables", async (req, res) => {
    try {
      const query = String(req.body?.query || "").trim();
      if (!query) {
        res.status(400).json({ error: "Query is required" });
        return;
      }
      const data = await runPythonPhase2(["retrieve", query]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to retrieve tables" });
    }
  });

  app.get("/api/phase1/table/:name", async (req, res) => {
    try {
      const name = String(req.params.name || "").replace(/[^a-zA-Z0-9_]/g, "");
      const data = await runPythonInspector(["table", name]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to inspect table" });
    }
  });

  app.get("/api/phase1/pdf/:filename", async (req, res) => {
    try {
      const safeName = path.basename(String(req.params.filename || ""));
      const data = await runPythonInspector(["pdf", safeName]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to extract PDF text" });
    }
  });

  app.get("/api/phase1/pdf-raw/:filename", (req, res) => {
    const safeName = path.basename(String(req.params.filename || ""));
    const fullPath = path.resolve(ROOT, "data", "pdfs", safeName);
    if (!fs.existsSync(fullPath)) {
      res.status(404).json({ error: "PDF not found" });
      return;
    }
    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Content-Disposition", `inline; filename="${safeName}"`);
    fs.createReadStream(fullPath).pipe(res);
  });

  app.post("/api/phase1/verify", async (_req, res) => {
    try {
      const data = await runPythonPhase2(["test"]);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err instanceof Error ? err.message : "Failed to run tests" });
    }
  });

  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distDir = path.resolve(ROOT, "dist");
    app.use(express.static(distDir));
    app.get("*", (_req, res) => {
      res.sendFile(path.join(distDir, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server listening on http://localhost:${PORT}`);
  });
}

startServer();

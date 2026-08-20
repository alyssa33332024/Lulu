import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express from "express";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname);
const DESKTOP = path.resolve(ROOT, "..", "Lulu-archive", "desktop");
const ZOME_IMG = path.resolve(DESKTOP, "assets", "I_Zome.png");
const PORT = Number(process.env.PORT || 3920);

let petProc = null;
let lastLog = "";

function portOpen(port) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: "127.0.0.1", port, path: "/", timeout: 800 },
      (res) => {
        res.resume();
        resolve(true);
      },
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function petStatus() {
  const brain = await portOpen(8000);
  const vite = await portOpen(5173);
  const running = Boolean(petProc && !petProc.killed) || (brain && vite);
  return {
    running,
    pid: petProc?.pid ?? null,
    brain,
    vite,
    desktop: DESKTOP,
    lastLog: lastLog.slice(-400),
  };
}

function launchPet() {
  if (petProc && !petProc.killed) {
    return { ok: true, already: true, pid: petProc.pid };
  }
  if (!fs.existsSync(path.join(DESKTOP, "package.json"))) {
    return { ok: false, error: `找不到桌宠目录：${DESKTOP}` };
  }

  try {
    // Windows: 直接 spawn npm.cmd 常报 EINVAL，需 shell
    petProc = spawn("npm start", {
      cwd: DESKTOP,
      env: { ...process.env },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
      shell: true,
    });
  } catch (err) {
    petProc = null;
    return { ok: false, error: `启动失败：${err.message || err}` };
  }

  const onChunk = (buf) => {
    lastLog = (lastLog + buf.toString("utf8")).slice(-4000);
  };
  petProc.stdout?.on("data", onChunk);
  petProc.stderr?.on("data", onChunk);
  petProc.on("error", (err) => {
    lastLog += `\n[spawn error] ${err.message}\n`;
    petProc = null;
  });
  petProc.on("exit", (code) => {
    lastLog += `\n[exit ${code}]\n`;
    petProc = null;
  });

  return { ok: true, already: false, pid: petProc.pid };
}

const app = express();
app.use(express.json());

app.get("/api/status", async (_req, res) => {
  res.json(await petStatus());
});

app.post("/api/launch", async (_req, res) => {
  try {
    const status = await petStatus();
    if (status.running && !petProc) {
      res.json({ ok: true, already: true, message: "桌宠似乎已在运行", ...status });
      return;
    }
    const result = launchPet();
    if (!result.ok) {
      res.status(500).json(result);
      return;
    }
    res.json({
      ok: true,
      already: result.already,
      pid: result.pid,
      message: result.already ? "桌宠已在运行" : "正在打开 LuLu 桌宠…",
    });
  } catch (err) {
    res.status(500).json({ ok: false, error: String(err?.message || err) });
  }
});

app.get("/assets/zome.png", (_req, res) => {
  if (!fs.existsSync(ZOME_IMG)) {
    res.status(404).end("missing");
    return;
  }
  res.sendFile(ZOME_IMG);
});

app.use(express.static(path.join(ROOT, "public")));

app.listen(PORT, "127.0.0.1", () => {
  console.log(`[lulu-portal] http://127.0.0.1:${PORT}`);
  console.log(`[lulu-portal] desktop → ${DESKTOP}`);
});

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const CACHE_PATH = path.join(os.homedir(), ".codex", "codex-discord-runtime.json");

interface RuntimeCache {
  codexCommand?: string;
}

function loadCache(): RuntimeCache {
  try {
    return JSON.parse(fs.readFileSync(CACHE_PATH, "utf-8")) as RuntimeCache;
  } catch {
    return {};
  }
}

function saveCache(cache: RuntimeCache): void {
  try {
    fs.mkdirSync(path.dirname(CACHE_PATH), { recursive: true });
    fs.writeFileSync(CACHE_PATH, JSON.stringify(cache, null, 2));
  } catch {
    // ignore cache write failures
  }
}

function commandWorks(command: string): boolean {
  try {
    const result = spawnSync(command, ["--version"], {
      encoding: "utf-8",
      windowsHide: true,
      timeout: 10_000,
    });
    return result.status === 0;
  } catch {
    return false;
  }
}

export function resolveCodexCommand(): string {
  if (process.platform !== "win32") return "codex";

  const cache = loadCache();
  if (cache.codexCommand && commandWorks(cache.codexCommand)) {
    return cache.codexCommand;
  }

  const candidates = ["codex.cmd", "codex.exe", "codex"];
  for (const candidate of candidates) {
    if (!commandWorks(candidate)) continue;
    saveCache({ ...cache, codexCommand: candidate });
    return candidate;
  }

  return "codex.cmd";
}

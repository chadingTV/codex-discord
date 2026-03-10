import os from "node:os";
import path from "node:path";
import fs from "node:fs";
import Database from "better-sqlite3";

export interface StoredCodexThread {
  id: string;
  rollout_path: string;
  created_at: number;
  updated_at: number;
  source: string;
  model_provider: string;
  cwd: string;
  title: string;
}

function getCodexHome(): string {
  return path.join(os.homedir(), ".codex");
}

export function findStateDbPath(): string | null {
  const codexHome = getCodexHome();
  if (!fs.existsSync(codexHome)) return null;

  const entries = fs
    .readdirSync(codexHome)
    .filter((name) => /^state_\d+\.sqlite$/.test(name))
    .map((name) => {
      const filePath = path.join(codexHome, name);
      return {
        filePath,
        mtimeMs: fs.statSync(filePath).mtimeMs,
      };
    })
    .sort((a, b) => b.mtimeMs - a.mtimeMs);

  return entries[0]?.filePath ?? null;
}

function openStateDb(readonly = true): Database.Database | null {
  const dbPath = findStateDbPath();
  if (!dbPath) return null;
  return new Database(dbPath, readonly ? { readonly: true } : undefined);
}

export function listStoredThreads(projectPath: string): StoredCodexThread[] {
  const db = openStateDb(true);
  if (!db) return [];

  try {
    return db
      .prepare(`
        SELECT id, rollout_path, created_at, updated_at, source, model_provider, cwd, title
        FROM threads
        WHERE cwd = ? AND archived = 0
        ORDER BY updated_at DESC
      `)
      .all(projectPath) as StoredCodexThread[];
  } finally {
    db.close();
  }
}

export function getStoredThread(threadId: string): StoredCodexThread | undefined {
  const db = openStateDb(true);
  if (!db) return undefined;

  try {
    return db
      .prepare(`
        SELECT id, rollout_path, created_at, updated_at, source, model_provider, cwd, title
        FROM threads
        WHERE id = ?
      `)
      .get(threadId) as StoredCodexThread | undefined;
  } finally {
    db.close();
  }
}

export function deleteStoredThread(threadId: string): boolean {
  const existing = getStoredThread(threadId);
  const db = openStateDb(false);
  if (!db || !existing) return false;

  try {
    const tx = db.transaction(() => {
      db.prepare("DELETE FROM logs WHERE thread_id = ?").run(threadId);
      db.prepare("DELETE FROM thread_dynamic_tools WHERE thread_id = ?").run(threadId);
      db.prepare("DELETE FROM threads WHERE id = ?").run(threadId);
    });
    tx();
  } finally {
    db.close();
  }

  try {
    if (existing.rollout_path && fs.existsSync(existing.rollout_path)) {
      fs.unlinkSync(existing.rollout_path);
    }
  } catch {
    // ignore
  }

  return true;
}

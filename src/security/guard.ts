import path from "node:path";
import fs from "node:fs";
import { getConfig } from "../utils/config.js";

// Rate limit: track requests per user
const requestCounts = new Map<string, { count: number; resetAt: number }>();

// Periodically clean up expired rate limit entries to prevent memory leak
setInterval(() => {
  const now = Date.now();
  for (const [key, entry] of requestCounts) {
    if (now > entry.resetAt) requestCounts.delete(key);
  }
}, 300_000); // every 5 minutes

export function isAllowedUser(userId: string): boolean {
  const config = getConfig();
  return config.ALLOWED_USER_IDS.includes(userId);
}

export function checkRateLimit(userId: string): boolean {
  const config = getConfig();
  const now = Date.now();
  const windowMs = 60_000; // 1 minute

  let entry = requestCounts.get(userId);
  if (!entry || now > entry.resetAt) {
    entry = { count: 0, resetAt: now + windowMs };
    requestCounts.set(userId, entry);
  }

  entry.count++;
  return entry.count <= config.RATE_LIMIT_PER_MINUTE;
}

export function validateProjectPath(projectPath: string): string | null {
  const resolved = path.resolve(projectPath);

  // Block path traversal
  if (projectPath.includes("..")) {
    return "Path must not contain '..'";
  }

  // Validate path is within BASE_PROJECT_DIR
  const config = getConfig();
  const baseDir = path.resolve(config.BASE_PROJECT_DIR);
  if (!resolved.startsWith(baseDir + path.sep) && resolved !== baseDir) {
    return `Path must be within ${baseDir}`;
  }

  // Check existence
  if (!fs.existsSync(resolved)) {
    return `Path does not exist: ${resolved}`;
  }

  // Check it's a directory
  if (!fs.statSync(resolved).isDirectory()) {
    return `Path is not a directory: ${resolved}`;
  }

  return null; // valid
}

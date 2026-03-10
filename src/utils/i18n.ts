import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Use import.meta.url to reliably find the bot root directory
// (dist/index.js -> dist/ -> botDir), regardless of process.cwd()
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LANG_FILE = path.join(__dirname, "..", ".tray-lang");

/**
 * Read the current language preference from .tray-lang file.
 * Returns "en" (default) or "kr".
 * Reads fresh from disk on each call so tray app changes take effect immediately.
 */
function getCurrentLang(): "en" | "kr" {
  try {
    const content = fs.readFileSync(LANG_FILE, "utf-8").trim();
    return content === "kr" ? "kr" : "en";
  } catch {
    return "en";
  }
}

/**
 * Localization helper. Returns the string matching the current language.
 * Usage: L("Hello", "안녕하세요")
 */
export function L(en: string, kr: string): string {
  return getCurrentLang() === "kr" ? kr : en;
}

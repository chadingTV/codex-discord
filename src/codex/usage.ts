import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { codexAppServer, type CodexRateLimitsResponse, type CodexRateLimitSnapshot, type CodexRateLimitWindow } from "./app-server-client.js";

export interface CodexUsageBucket {
  title: string | null;
  primary?: CodexRateLimitWindow;
  secondary?: CodexRateLimitWindow;
}

export interface CodexUsageData {
  planType?: string;
  buckets: CodexUsageBucket[];
}

export interface CachedCodexUsage {
  fetchedAt: number;
  usage: CodexUsageData;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readOptionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function readOptionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function readWindow(value: unknown): CodexRateLimitWindow | undefined {
  if (!isObject(value)) return undefined;

  const usedPercent = readOptionalNumber(value.usedPercent);
  if (usedPercent === undefined) return undefined;

  return {
    usedPercent,
    windowDurationMins: readOptionalNumber(value.windowDurationMins),
    resetsAt: readOptionalNumber(value.resetsAt),
  };
}

function readSnapshot(value: unknown): CodexRateLimitSnapshot | undefined {
  if (!isObject(value)) return undefined;

  const primary = readWindow(value.primary);
  const secondary = readWindow(value.secondary);
  if (!primary && !secondary) return undefined;

  return {
    limitId: readOptionalString(value.limitId),
    limitName: readOptionalString(value.limitName),
    planType: readOptionalString(value.planType),
    primary,
    secondary,
  };
}

function readBucket(value: unknown): CodexUsageBucket | undefined {
  if (!isObject(value)) return undefined;

  const primary = readWindow(value.primary);
  const secondary = readWindow(value.secondary);
  if (!primary && !secondary) return undefined;

  return {
    title: typeof value.title === "string" ? value.title : null,
    primary,
    secondary,
  };
}

function readUsageData(value: unknown): CodexUsageData | null {
  if (!isObject(value) || !Array.isArray(value.buckets)) return null;

  const buckets = value.buckets
    .map((bucket) => readBucket(bucket))
    .filter((bucket): bucket is CodexUsageBucket => Boolean(bucket));

  if (buckets.length === 0) return null;

  return {
    planType: readOptionalString(value.planType),
    buckets,
  };
}

function usageCachePath(): string {
  return path.join(os.homedir(), ".codex", "rate-limits-cache.json");
}

export function normalizeCodexUsage(result: CodexRateLimitsResponse | Record<string, unknown>): CodexUsageData | null {
  const existingUsage = readUsageData(result);
  if (existingUsage) return existingUsage;

  const snapshots = isObject(result.rateLimitsByLimitId) ? result.rateLimitsByLimitId : undefined;
  const primarySnapshot = readSnapshot(snapshots?.codex) ?? readSnapshot(result.rateLimits);
  if (!primarySnapshot) return null;

  return {
    planType: primarySnapshot.planType,
    buckets: [
      {
        title: null,
        primary: primarySnapshot.primary,
        secondary: primarySnapshot.secondary,
      },
    ],
  };
}

export async function fetchCodexUsage(): Promise<CodexUsageData | null> {
  const result = await codexAppServer.readRateLimits();
  const usage = normalizeCodexUsage(result);
  if (usage) {
    saveCodexUsageCache(usage);
  }
  return usage;
}

export function saveCodexUsageCache(usage: CodexUsageData, fetchedAt = Date.now()): void {
  const cachePath = usageCachePath();
  fs.mkdirSync(path.dirname(cachePath), { recursive: true });
  fs.writeFileSync(cachePath, JSON.stringify({ fetchedAt, usage }));
}

export function loadCodexUsageCache(): CachedCodexUsage | null {
  try {
    const raw = fs.readFileSync(usageCachePath(), "utf-8");
    const parsed = JSON.parse(raw) as { fetchedAt?: unknown; usage?: unknown };
    if (typeof parsed.fetchedAt !== "number" || !parsed.usage || !isObject(parsed.usage)) {
      return null;
    }

    const usage = readUsageData(parsed.usage);
    if (!usage) return null;

    return {
      fetchedAt: parsed.fetchedAt,
      usage,
    };
  } catch {
    return null;
  }
}

export function getCodexUsageRows(usage: CodexUsageData): Array<{ bucketTitle: string | null; window: CodexRateLimitWindow }> {
  const rows: Array<{ bucketTitle: string | null; window: CodexRateLimitWindow }> = [];

  for (const bucket of usage.buckets) {
    if (bucket.primary) {
      rows.push({ bucketTitle: bucket.title, window: bucket.primary });
    }
    if (bucket.secondary) {
      rows.push({ bucketTitle: null, window: bucket.secondary });
    }
  }

  return rows;
}

export function getUsagePercentLeft(window: CodexRateLimitWindow): number {
  return Math.max(0, Math.min(100, 100 - Math.round(window.usedPercent)));
}

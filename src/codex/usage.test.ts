import { describe, it, expect } from "vitest";
import { getCodexUsageRows, getUsagePercentLeft, normalizeCodexUsage } from "./usage.js";

describe("codex usage helpers", () => {
  it("normalizes the codex rate limit snapshot", () => {
    const usage = normalizeCodexUsage({
      rateLimits: {
        planType: "pro",
        primary: { usedPercent: 35, windowDurationMins: 300, resetsAt: 1_700_000_000 },
        secondary: { usedPercent: 60, windowDurationMins: 10080, resetsAt: 1_700_100_000 },
      },
      rateLimitsByLimitId: {
        codex: {
          planType: "pro",
          primary: { usedPercent: 35, windowDurationMins: 300, resetsAt: 1_700_000_000 },
          secondary: { usedPercent: 60, windowDurationMins: 10080, resetsAt: 1_700_100_000 },
        },
      },
    });

    expect(usage).toEqual({
      planType: "pro",
      buckets: [
        {
          title: null,
          primary: { usedPercent: 35, windowDurationMins: 300, resetsAt: 1_700_000_000 },
          secondary: { usedPercent: 60, windowDurationMins: 10080, resetsAt: 1_700_100_000 },
        },
      ],
    });
  });

  it("returns null when there is no usable rate limit window", () => {
    expect(
      normalizeCodexUsage({
        rateLimits: {
          planType: "pro",
        },
      }),
    ).toBeNull();
  });

  it("flattens primary and secondary usage windows into rows", () => {
    const rows = getCodexUsageRows({
      planType: "pro",
      buckets: [
        {
          title: "Codex",
          primary: { usedPercent: 10, windowDurationMins: 300, resetsAt: 1 },
          secondary: { usedPercent: 70, windowDurationMins: 10080, resetsAt: 2 },
        },
      ],
    });

    expect(rows).toEqual([
      { bucketTitle: "Codex", window: { usedPercent: 10, windowDurationMins: 300, resetsAt: 1 } },
      { bucketTitle: null, window: { usedPercent: 70, windowDurationMins: 10080, resetsAt: 2 } },
    ]);
  });

  it("converts used percent into remaining percent", () => {
    expect(getUsagePercentLeft({ usedPercent: 35 })).toBe(65);
    expect(getUsagePercentLeft({ usedPercent: 140 })).toBe(0);
    expect(getUsagePercentLeft({ usedPercent: -20 })).toBe(100);
  });
});

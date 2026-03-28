import { ChatInputCommandInteraction, SlashCommandBuilder, EmbedBuilder } from "discord.js";
import { L } from "../../utils/i18n.js";
import { fetchCodexUsage, getCodexUsageRows, getUsagePercentLeft, loadCodexUsageCache, type CodexUsageData } from "../../codex/usage.js";

export const data = new SlashCommandBuilder()
  .setName("usage")
  .setDescription("Show Codex usage from your local account");

function progressBar(percentLeft: number, width = 12): string {
  const filled = Math.round((percentLeft / 100) * width);
  return "█".repeat(filled) + "░".repeat(width - filled);
}

function formatResetText(
  resetsAt: number | undefined,
  now: Date,
): string {
  if (!resetsAt) return "";

  const resetDate = new Date(resetsAt * 1000);
  const sameDay =
    resetDate.getFullYear() === now.getFullYear() &&
    resetDate.getMonth() === now.getMonth() &&
    resetDate.getDate() === now.getDate();

  if (sameDay) {
    const formatted = resetDate.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
    return L(`Resets ${formatted}`, `${formatted} 초기화`);
  }

  const formatted = resetDate.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  return L(`Resets on ${formatted}`, `${formatted} 초기화`);
}

function usageLabel(windowDurationMins: number | undefined): string {
  if (windowDurationMins === 300) {
    return L("5-hour limit", "5시간 한도");
  }
  if (windowDurationMins === 10080) {
    return L("7-day limit", "7일 한도");
  }
  if (windowDurationMins) {
    return L(`${windowDurationMins}-minute limit`, `${windowDurationMins}분 한도`);
  }
  return L("Usage limit", "사용량 한도");
}

function footerText(fetchedAt: number | null, now = Date.now()): string {
  const suffix = "chatgpt.com/codex/settings/usage";
  if (!fetchedAt) return suffix;

  const diffMin = Math.floor((now - fetchedAt) / 60000);
  if (diffMin < 1) {
    return `${L("Just now", "방금 갱신")}  ·  ${suffix}`;
  }
  return `${L(`${diffMin}m ago`, `${diffMin}분 전 갱신`)}  ·  ${suffix}`;
}

function describeUsage(usage: CodexUsageData): string {
  const rows = getCodexUsageRows(usage);
  const now = new Date();
  const lines: string[] = [];

  for (const row of rows) {
    if (row.bucketTitle) {
      lines.push(`**${row.bucketTitle}**`);
    }

    const percentLeft = getUsagePercentLeft(row.window);
    const reset = formatResetText(row.window.resetsAt, now);
    lines.push(
      `**${usageLabel(row.window.windowDurationMins)}**  \`${progressBar(percentLeft)}\`  **${percentLeft}% ${L("left", "남음")}**${reset ? `  ·  ${reset}` : ""}`,
    );
  }

  if (usage.planType) {
    lines.unshift(`**${L("Plan", "플랜")}**: \`${usage.planType}\``);
  }

  return lines.join("\n\n");
}

export async function execute(interaction: ChatInputCommandInteraction): Promise<void> {
  let usage: CodexUsageData | null = null;
  let fetchedAt: number | null = null;

  try {
    usage = await fetchCodexUsage();
    if (usage) {
      fetchedAt = Date.now();
    }
  } catch {
    // fall back to cache below
  }

  if (!usage) {
    const cached = loadCodexUsageCache();
    usage = cached?.usage ?? null;
    fetchedAt = cached?.fetchedAt ?? null;
  }

  if (!usage || getCodexUsageRows(usage).length === 0) {
    await interaction.editReply({
      content: L(
        "Could not fetch Codex usage data. Make sure `codex login status` shows a logged-in account.",
        "Codex 사용량 정보를 가져오지 못했습니다. `codex login status`에서 로그인된 계정을 확인하세요.",
      ),
    });
    return;
  }

  const embed = new EmbedBuilder()
    .setTitle(L("📊 Codex Usage", "📊 Codex 사용량"))
    .setDescription(describeUsage(usage))
    .setColor(0x10b981)
    .setFooter({ text: footerText(fetchedAt) })
    .setTimestamp();

  await interaction.editReply({ embeds: [embed] });
}

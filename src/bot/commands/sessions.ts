import {
  ChatInputCommandInteraction,
  SlashCommandBuilder,
  ActionRowBuilder,
  StringSelectMenuBuilder,
} from "discord.js";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { getProject, getSession, upsertSession } from "../../db/database.js";
import { listStoredThreads } from "../../codex/storage.js";
import { L } from "../../utils/i18n.js";

interface SessionInfo {
  sessionId: string;
  preview: string;
  timestamp: string;
  source: string;
}

export function findSessionDir(projectPath: string): string | null {
  const first = listStoredThreads(projectPath)[0];
  return first?.rollout_path ? path.dirname(first.rollout_path) : null;
}

export async function getLastAssistantMessage(filePath: string): Promise<string> {
  const full = await getLastAssistantMessageFull(filePath);
  if (full === "(no message)") return full;
  const lines = full.split("\n").map((line) => line.trim()).filter(Boolean);
  return lines[lines.length - 1] || full.slice(-200);
}

export async function getLastAssistantMessageFull(filePath: string): Promise<string> {
  const stream = fs.createReadStream(filePath, { encoding: "utf-8" });
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
  let lastText = "";

  for await (const line of rl) {
    try {
      const entry = JSON.parse(line);
      if (entry.type === "response_item" && entry.payload?.type === "message") {
        const content = entry.payload?.content ?? [];
        const text = Array.isArray(content)
          ? content
              .map((item: { text?: string }) => item?.text ?? "")
              .join("")
              .trim()
          : "";
        if (text) lastText = text;
      }

      if (entry.type === "item_completed" && entry.item?.type === "agentMessage" && typeof entry.item.text === "string") {
        const text = entry.item.text.trim();
        if (text) lastText = text;
      }
    } catch {
      // skip malformed lines
    }
  }

  rl.close();
  stream.destroy();
  return lastText || "(no message)";
}

export async function listSessions(projectPath: string): Promise<SessionInfo[]> {
  return listStoredThreads(projectPath).map((thread) => ({
    sessionId: thread.id,
    preview: thread.title || "(empty session)",
    timestamp: new Date(thread.updated_at * 1000).toISOString(),
    source: thread.source,
  }));
}

export const data = new SlashCommandBuilder()
  .setName("sessions")
  .setDescription("List and resume existing Codex sessions for this project");

export async function execute(
  interaction: ChatInputCommandInteraction,
): Promise<void> {
  const channelId = interaction.channelId;
  const project = getProject(channelId);

  if (!project) {
    await interaction.editReply({
      content: L("This channel is not registered to any project. Use `/register` first.", "이 채널은 어떤 프로젝트에도 등록되어 있지 않습니다. 먼저 `/register`를 사용하세요."),
    });
    return;
  }

  const sessions = await listSessions(project.project_path);

  if (sessions.length === 0) {
    const { randomUUID } = await import("node:crypto");
    upsertSession(randomUUID(), channelId, null, "idle");
    await interaction.editReply({
      embeds: [
        {
          title: L("✨ New Session", "✨ 새 세션"),
          description: L(
            `No existing Codex sessions found for \`${project.project_path}\`.\nA new session is ready — your next message will start a new conversation.`,
            `\`${project.project_path}\`에 대한 기존 Codex 세션이 없습니다.\n새 세션이 준비되었습니다 — 다음 메시지부터 새로운 대화가 시작됩니다.`
          ),
          color: 0x00ff00,
        },
      ],
    });
    return;
  }

  const dbSession = getSession(channelId);
  const activeSessionId = dbSession?.session_id ?? null;

  const options: Array<{ label: string; description: string; value: string; default?: boolean }> = [
    {
      label: L("✨ Create New Session", "✨ 새 세션 만들기"),
      description: L("Start a new conversation without an existing session", "기존 세션 없이 새로운 대화를 시작합니다"),
      value: "__new_session__",
    },
  ];

  for (const session of sessions.slice(0, 24)) {
    const preview = session.preview.length > 70 ? session.preview.slice(0, 70) + "…" : session.preview;
    const date = new Date(session.timestamp).toLocaleString();
    options.push({
      label: preview || "(empty session)",
      description: `${session.source} • ${date}`,
      value: session.sessionId,
      ...(activeSessionId === session.sessionId ? { default: true } : {}),
    });
  }

  const select = new StringSelectMenuBuilder()
    .setCustomId("session-select")
    .setPlaceholder(L("Select a session to inspect or resume", "확인하거나 재개할 세션을 선택하세요"))
    .addOptions(options);

  const row = new ActionRowBuilder<StringSelectMenuBuilder>().addComponents(select);

  await interaction.editReply({
    embeds: [
      {
        title: L("Codex Sessions", "Codex 세션"),
        description: L(
          `Project: \`${project.project_path}\`\nChoose a session to view its last response, resume it, or delete it.`,
          `프로젝트: \`${project.project_path}\`\n세션을 선택하면 마지막 응답을 보고, 재개하거나, 삭제할 수 있습니다.`
        ),
        color: 0x5865f2,
      },
    ],
    components: [row],
  });
}

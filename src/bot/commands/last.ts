import {
  ChatInputCommandInteraction,
  SlashCommandBuilder,
} from "discord.js";
import { getProject, getSession } from "../../db/database.js";
import { codexAppServer } from "../../codex/app-server-client.js";
import { splitMessage } from "../../codex/output-formatter.js";
import { L } from "../../utils/i18n.js";

export const data = new SlashCommandBuilder()
  .setName("last")
  .setDescription("Show the last Codex response from the current session");

export async function execute(
  interaction: ChatInputCommandInteraction,
): Promise<void> {
  const channelId = interaction.channelId;
  const project = getProject(channelId);

  if (!project) {
    await interaction.editReply({
      content: L("This channel is not registered to any project. Use `/register` first.", "이 채널은 프로젝트에 등록되지 않았습니다. `/register`를 먼저 사용하세요."),
    });
    return;
  }

  const session = getSession(channelId);
  if (!session?.session_id) {
    await interaction.editReply({
      content: L("No active session. Select a session from `/sessions`.", "활성 세션이 없습니다. `/sessions`에서 세션을 선택하세요."),
    });
    return;
  }

  const thread = await codexAppServer.readThread(session.session_id, true);
  let lastMessage = "";

  for (const turn of thread.turns ?? []) {
    for (const item of turn.items ?? []) {
      if (item.type === "agentMessage" && typeof item.text === "string" && item.text.trim()) {
        lastMessage = item.text.trim();
      }
    }
  }

  if (!lastMessage) {
    await interaction.editReply({
      content: L("No Codex response in this session.", "이 세션에 Codex 응답이 없습니다."),
    });
    return;
  }

  const chunks = splitMessage(lastMessage);
  await interaction.editReply({ content: chunks[0] });
  for (let i = 1; i < chunks.length; i++) {
    await interaction.followUp({ content: chunks[i] });
  }
}

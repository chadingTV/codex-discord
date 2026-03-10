import {
  ChatInputCommandInteraction,
  SlashCommandBuilder,
} from "discord.js";
import { getProject } from "../../db/database.js";
import { sessionManager } from "../../codex/session-manager.js";
import { L } from "../../utils/i18n.js";

export const data = new SlashCommandBuilder()
  .setName("stop")
  .setDescription("Stop the active Codex session in this channel");

export async function execute(
  interaction: ChatInputCommandInteraction,
): Promise<void> {
  const channelId = interaction.channelId;
  const project = getProject(channelId);

  if (!project) {
    await interaction.editReply({
      content: L("This channel is not registered to any project.", "이 채널은 어떤 프로젝트에도 등록되어 있지 않습니다."),
    });
    return;
  }

  const stopped = await sessionManager.stopSession(channelId);
  if (stopped) {
    await interaction.editReply({
      embeds: [
        {
          title: L("Session Stopped", "세션 중지됨"),
          description: L(`Stopped Codex session for \`${project.project_path}\``, `\`${project.project_path}\` Codex 세션이 중지되었습니다`),
          color: 0xff6600,
        },
      ],
    });
  } else {
    await interaction.editReply({
      content: L("No active session in this channel.", "이 채널에 활성 세션이 없습니다."),
    });
  }
}

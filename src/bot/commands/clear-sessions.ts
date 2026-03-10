import {
  ChatInputCommandInteraction,
  SlashCommandBuilder,
  PermissionFlagsBits,
} from "discord.js";
import { getProject } from "../../db/database.js";
import { deleteStoredThread, listStoredThreads } from "../../codex/storage.js";
import { L } from "../../utils/i18n.js";

export const data = new SlashCommandBuilder()
  .setName("clear-sessions")
  .setDescription("Delete all Codex session files for this project")
  .setDefaultMemberPermissions(PermissionFlagsBits.Administrator);

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

  const threads = listStoredThreads(project.project_path);
  if (threads.length === 0) {
    await interaction.editReply({
      content: L("No session files to delete.", "삭제할 세션 파일이 없습니다."),
    });
    return;
  }

  let deleted = 0;
  for (const thread of threads) {
    if (deleteStoredThread(thread.id)) deleted++;
  }

  await interaction.editReply({
    embeds: [
      {
        title: L("Sessions Cleared", "세션 정리됨"),
        description: [
          `Project: \`${project.project_path}\``,
          L(`Deleted **${deleted}** session(s)`, `**${deleted}**개의 세션이 삭제되었습니다`),
        ].join("\n"),
        color: 0xff6b6b,
      },
    ],
  });
}

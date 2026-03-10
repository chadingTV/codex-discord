import {
  ChatInputCommandInteraction,
  SlashCommandBuilder,
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
} from "discord.js";
import { getProject } from "../../db/database.js";
import { sessionManager } from "../../codex/session-manager.js";
import { L } from "../../utils/i18n.js";

export const data = new SlashCommandBuilder()
  .setName("queue")
  .setDescription("View and manage queued messages in this channel")
  .addSubcommand((sub) =>
    sub.setName("list").setDescription("Show all queued messages")
  )
  .addSubcommand((sub) =>
    sub.setName("clear").setDescription("Clear all queued messages")
  );

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

  const subcommand = interaction.options.getSubcommand();

  if (subcommand === "list") {
    const queue = sessionManager.getQueue(channelId);
    if (queue.length === 0) {
      await interaction.editReply({
        content: L("No messages in queue.", "큐에 대기 중인 메시지가 없습니다."),
      });
      return;
    }

    const list = queue
      .map((item, idx) => {
        const preview = item.prompt.length > 100 ? item.prompt.slice(0, 100) + "…" : item.prompt;
        return `**${idx + 1}.** ${preview}`;
      })
      .join("\n\n");

    const rows: ActionRowBuilder<ButtonBuilder>[] = [];
    const itemButtons: ButtonBuilder[] = queue.map((_, idx) =>
      new ButtonBuilder()
        .setCustomId(`queue-remove:${channelId}:${idx}`)
        .setLabel(`❌ ${idx + 1}`)
        .setStyle(ButtonStyle.Secondary)
    );

    const clearButton = new ButtonBuilder()
      .setCustomId(`queue-clear:${channelId}`)
      .setLabel(L("Clear All", "모두 취소"))
      .setStyle(ButtonStyle.Danger);

    const allButtons = [...itemButtons.slice(0, 19), clearButton];
    for (let i = 0; i < allButtons.length; i += 5) {
      const chunk = allButtons.slice(i, i + 5);
      rows.push(new ActionRowBuilder<ButtonBuilder>().addComponents(...chunk));
    }

    await interaction.editReply({
      embeds: [
        {
          title: L(`📋 Message Queue (${queue.length})`, `📋 메시지 큐 (${queue.length}개)`),
          description: list,
          color: 0x5865f2,
        },
      ],
      components: rows,
    });
    return;
  }

  const cleared = sessionManager.clearQueue(channelId);
  await interaction.editReply({
    embeds: [
      {
        title: L("Queue Cleared", "큐 초기화됨"),
        description: L(`Cleared ${cleared} queued message(s).`, `${cleared}개의 대기 중이던 메시지를 취소했습니다.`),
        color: 0xff6600,
      },
    ],
  });
}

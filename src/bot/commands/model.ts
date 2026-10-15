import {
  ChatInputCommandInteraction,
  AutocompleteInteraction,
  SlashCommandBuilder,
} from "discord.js";
import {
  getProject,
  setProjectModel,
  setProjectReasoningEffort,
} from "../../db/database.js";
import { codexAppServer } from "../../codex/app-server-client.js";

export const data = new SlashCommandBuilder()
  .setName("model")
  .setDescription("Select the Codex model for this Discord channel")
  .addStringOption((option) =>
    option
      .setName("name")
      .setDescription("Codex model (start typing to search)")
      .setRequired(true)
      .setAutocomplete(true),
  );

export async function execute(
  interaction: ChatInputCommandInteraction,
): Promise<void> {
  const channelId = interaction.channelId;
  const model = interaction.options.getString("name", true);
  const project = getProject(channelId);

  if (!project) {
    await interaction.editReply({
      content: "This channel is not registered to any project.",
    });
    return;
  }

  if (model === "default") {
    setProjectModel(channelId, null);
    setProjectReasoningEffort(channelId, null);

    await interaction.editReply({
      content: "Model and reasoning preferences reset to Codex defaults for this channel.",
    });
    return;
  }

  let result: Awaited<ReturnType<typeof codexAppServer.listModels>>;

  try {
    result = await codexAppServer.listModels();
  } catch (error) {
    console.error("Failed to retrieve Codex models:", error);

    await interaction.editReply({
      content: "❌ Could not retrieve Codex models. Please try again later.",
    });
    return;
  }

  const selected = result.data.find(
    (item) => !item.hidden && item.model === model,
  );

  if (!selected) {
    await interaction.editReply({
      content: `Unknown or unavailable Codex model: ${model}`,
    });
    return;
  }

  setProjectModel(channelId, selected.model);

  if (project.model !== selected.model) {
    setProjectReasoningEffort(channelId, null);
  }

  await interaction.editReply({
    content: `Codex model for this channel set to **${selected.displayName}**.`,
  });
}

export async function autocomplete(
  interaction: AutocompleteInteraction,
): Promise<void> {
  const query = interaction.options.getFocused().toLowerCase();

  try {
    const result = await codexAppServer.listModels();

    const choices = [
      { name: "Default (Codex default model)", value: "default" },
      ...result.data
        .filter((model) => !model.hidden)
        .map((model) => ({
          name: model.displayName,
          value: model.model,
        })),
    ];

    const filtered = choices
      .filter(
        (choice) =>
          choice.name.toLowerCase().includes(query) ||
          choice.value.toLowerCase().includes(query),
      )
      .slice(0, 25);

    await interaction.respond(filtered);
  } catch (error) {
    console.error("Failed to retrieve Codex models:", error);
    await interaction.respond([]);
  }
}

import {
  ChatInputCommandInteraction,
  AutocompleteInteraction,
  SlashCommandBuilder,
} from "discord.js";
import {
  getProject,
  setProjectReasoningEffort,
} from "../../db/database.js";
import { codexAppServer } from "../../codex/app-server-client.js";

export const data = new SlashCommandBuilder()
  .setName("reasoning")
  .setDescription("Select Codex reasoning effort for this channel")
  .addStringOption((option) =>
    option
      .setName("level")
      .setDescription("Reasoning level (start typing to search)")
      .setRequired(true)
      .setAutocomplete(true),
  );

export async function execute(
  interaction: ChatInputCommandInteraction,
): Promise<void> {
  const channelId = interaction.channelId;
  const level = interaction.options.getString("level", true);
  const project = getProject(channelId);

  if (!project) {
    await interaction.editReply({
      content: "This channel is not registered to any project.",
    });
    return;
  }

  if (level === "default") {
    setProjectReasoningEffort(channelId, null);
    await interaction.editReply({
      content: "Reasoning preference reset to the selected model's default.",
    });
    return;
  }

  let result: Awaited<ReturnType<typeof codexAppServer.listModels>>;

  try {
    result = await codexAppServer.listModels();
  } catch (error) {
    console.error("Failed to retrieve Codex reasoning models:", error);
    await interaction.editReply({
      content: "❌ Could not retrieve Codex models. Please try again later.",
    });
    return;
  }

  const selectedModel = project.model
    ? result.data.find(
        (model) => !model.hidden && model.model === project.model,
      )
    : result.data.find((model) => model.isDefault);

  if (!selectedModel) {
    await interaction.editReply({
      content: "Could not determine the channel's Codex model.",
    });
    return;
  }

  const supported = selectedModel.supportedReasoningEfforts.some(
    (option) => option.reasoningEffort === level,
  );

  if (!supported) {
    await interaction.editReply({
      content: `Reasoning level "${level}" is not supported by ${selectedModel.displayName}.`,
    });
    return;
  }

  setProjectReasoningEffort(channelId, level);

  await interaction.editReply({
    content: `Reasoning level for this channel set to **${level}** (${selectedModel.displayName}).`,
  });
}

export async function autocomplete(
  interaction: AutocompleteInteraction,
): Promise<void> {
  const project = getProject(interaction.channelId);

  if (!project) {
    await interaction.respond([]);
    return;
  }

  try {
    const result = await codexAppServer.listModels();

    const selectedModel = project.model
      ? result.data.find(
          (model) => !model.hidden && model.model === project.model,
        )
      : result.data.find((model) => model.isDefault);

    if (!selectedModel) {
      await interaction.respond([]);
      return;
    }

    const query = interaction.options.getFocused().toLowerCase();

    const choices = [
      {
        name: `Default (${selectedModel.defaultReasoningEffort})`,
        value: "default",
      },
      ...selectedModel.supportedReasoningEfforts.map((option) => ({
        name: option.reasoningEffort,
        value: option.reasoningEffort,
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
    console.error("Failed to retrieve reasoning levels:", error);
    await interaction.respond([]);
  }
}

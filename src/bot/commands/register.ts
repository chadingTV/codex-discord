import {
  ChatInputCommandInteraction,
  AutocompleteInteraction,
  SlashCommandBuilder,
  PermissionFlagsBits,
} from "discord.js";
import fs from "node:fs";
import path from "node:path";
import { registerProject, getProject } from "../../db/database.js";
import { validateProjectPath } from "../../security/guard.js";
import { getConfig } from "../../utils/config.js";
import { L } from "../../utils/i18n.js";

export const data = new SlashCommandBuilder()
  .setName("register")
  .setDescription("Register this channel to a project directory")
  .addStringOption((opt) =>
    opt
      .setName("path")
      .setDescription(`Project folder name (${getConfig().BASE_PROJECT_DIR})`)
      .setRequired(true)
      .setAutocomplete(true),
  )
  .setDefaultMemberPermissions(PermissionFlagsBits.Administrator);

export async function execute(
  interaction: ChatInputCommandInteraction,
): Promise<void> {
  const input = interaction.options.getString("path", true);
  const config = getConfig();
  // If input is absolute path, use as-is; otherwise join with base dir
  const projectPath = path.isAbsolute(input)
    ? input
    : path.join(config.BASE_PROJECT_DIR, input);
  const channelId = interaction.channelId;
  const guildId = interaction.guildId!;

  // Check if already registered
  const existing = getProject(channelId);
  if (existing) {
    await interaction.editReply({
      content: L(`This channel is already registered to \`${existing.project_path}\`. Use \`/unregister\` first.`, `이 채널은 이미 \`${existing.project_path}\`에 등록되어 있습니다. 먼저 \`/unregister\`를 사용하세요.`),
    });
    return;
  }

  // Create directory if it doesn't exist (new project)
  if (!fs.existsSync(projectPath)) {
    const resolved = path.resolve(projectPath);
    const baseDir = path.resolve(config.BASE_PROJECT_DIR);
    if (!resolved.startsWith(baseDir + path.sep) && resolved !== baseDir) {
      await interaction.editReply({ content: L(`Invalid path: Path must be within ${baseDir}`, `잘못된 경로: ${baseDir} 내에 있어야 합니다`) });
      return;
    }
    if (projectPath.includes("..")) {
      await interaction.editReply({ content: L("Invalid path: Path must not contain '..'", "잘못된 경로: '..'을 포함할 수 없습니다") });
      return;
    }
    fs.mkdirSync(projectPath, { recursive: true });
  }

  // Validate path
  const error = validateProjectPath(projectPath);
  if (error) {
    await interaction.editReply({ content: L(`Invalid path: ${error}`, `잘못된 경로: ${error}`) });
    return;
  }

  registerProject(channelId, projectPath, guildId);

  await interaction.editReply({
    embeds: [
      {
        title: L("Project Registered", "프로젝트 등록됨"),
        description: L(`This channel is now linked to:\n\`${projectPath}\``, `이 채널이 연결되었습니다:\n\`${projectPath}\``),
        color: 0x00ff00,
        fields: [
          { name: L("Status", "상태"), value: L("🔴 Offline", "🔴 오프라인"), inline: true },
          { name: L("Auto-approve", "자동 승인"), value: L("Off", "꺼짐"), inline: true },
        ],
      },
    ],
  });
}

export async function autocomplete(
  interaction: AutocompleteInteraction,
): Promise<void> {
  const focused = interaction.options.getFocused();
  const config = getConfig();
  const baseDir = config.BASE_PROJECT_DIR;

  try {
    const entries = fs.readdirSync(baseDir, { withFileTypes: true });
    const dirs = entries
      .filter((e) => e.isDirectory() && !e.name.startsWith("."))
      .map((e) => e.name)
      .filter((name) => name.toLowerCase().includes(focused.toLowerCase()))
      .slice(0, 24); // Discord max 25, reserve 1 for base dir

    const choices: { name: string; value: string }[] = [];
    // Add base directory itself as first option
    if (!focused || ".".includes(focused.toLowerCase()) || baseDir.toLowerCase().includes(focused.toLowerCase())) {
      choices.push({ name: `. (${baseDir})`, value: baseDir });
    }
    choices.push(...dirs.map((name) => ({ name, value: name })));

    // If user typed something that doesn't exactly match any existing dir, offer to create it
    if (focused && !dirs.some((d) => d.toLowerCase() === focused.toLowerCase())) {
      choices.push({ name: `📁 Create new: ${focused}`, value: focused });
    }

    await interaction.respond(choices.slice(0, 25));
  } catch {
    await interaction.respond([]);
  }
}

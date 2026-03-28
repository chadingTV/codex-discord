import fs from "node:fs";
import path from "node:path";

export interface RegisterAutocompleteChoice {
  name: string;
  value: string;
}

export function listProjectAutocompleteChoices(
  baseDir: string,
  focused: string,
): RegisterAutocompleteChoice[] {
  const lastSlash = focused.lastIndexOf("/");
  const parentPart = lastSlash >= 0 ? focused.slice(0, lastSlash) : "";
  const currentPrefix = lastSlash >= 0 ? focused.slice(lastSlash + 1) : focused;

  const listDir = parentPart ? path.join(baseDir, parentPart) : baseDir;
  const resolvedList = path.resolve(listDir);
  const resolvedBase = path.resolve(baseDir);
  if (!resolvedList.startsWith(resolvedBase + path.sep) && resolvedList !== resolvedBase) {
    return [];
  }

  const entries = fs.readdirSync(listDir, { withFileTypes: true });
  const dirs = entries
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
    .map((entry) => entry.name)
    .filter((name) => name.toLowerCase().includes(currentPrefix.toLowerCase()))
    .slice(0, 24);

  const choices: RegisterAutocompleteChoice[] = [];
  if (!parentPart && (!focused || ".".includes(focused.toLowerCase()) || baseDir.toLowerCase().includes(focused.toLowerCase()))) {
    choices.push({ name: `. (${baseDir})`, value: baseDir });
  }

  choices.push(
    ...dirs.map((name) => {
      const value = parentPart ? `${parentPart}/${name}` : name;
      return { name: value, value };
    }),
  );

  if (focused && !dirs.some((dir) => dir.toLowerCase() === currentPrefix.toLowerCase())) {
    choices.push({ name: `📁 Create new: ${focused}`, value: focused });
  }

  return choices.slice(0, 25);
}

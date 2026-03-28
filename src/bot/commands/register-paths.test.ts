import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { listProjectAutocompleteChoices } from "./register-paths.js";

describe("register path autocomplete", () => {
  let baseDir: string;

  beforeEach(() => {
    baseDir = fs.mkdtempSync(path.join(os.tmpdir(), "codex-register-"));
    fs.mkdirSync(path.join(baseDir, "frontend"));
    fs.mkdirSync(path.join(baseDir, "apps"));
    fs.mkdirSync(path.join(baseDir, "apps", "api-server"), { recursive: true });
    fs.mkdirSync(path.join(baseDir, ".hidden"));
  });

  afterEach(() => {
    fs.rmSync(baseDir, { recursive: true, force: true });
  });

  it("lists root directories and the base dir option", () => {
    const choices = listProjectAutocompleteChoices(baseDir, "");

    expect(choices[0]).toEqual({ name: `. (${baseDir})`, value: baseDir });
    expect(choices).toContainEqual({ name: "frontend", value: "frontend" });
    expect(choices).toContainEqual({ name: "apps", value: "apps" });
    expect(choices.find((choice) => choice.value === ".hidden")).toBeUndefined();
  });

  it("lists nested directories when a parent path is typed", () => {
    const choices = listProjectAutocompleteChoices(baseDir, "apps/ap");
    expect(choices).toContainEqual({ name: "apps/api-server", value: "apps/api-server" });
  });

  it("returns no results when the requested parent escapes the base dir", () => {
    expect(listProjectAutocompleteChoices(baseDir, "../")).toEqual([]);
  });

  it("offers a create option for unmatched input", () => {
    const choices = listProjectAutocompleteChoices(baseDir, "new-project");
    expect(choices).toContainEqual({ name: "📁 Create new: new-project", value: "new-project" });
  });
});

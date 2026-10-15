import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../db/database.js", () => ({
  getProject: vi.fn(),
  setProjectModel: vi.fn(),
  setProjectReasoningEffort: vi.fn(),
}));
vi.mock("../../codex/app-server-client.js", () => ({
  codexAppServer: { listModels: vi.fn() },
}));

import { getProject, setProjectModel, setProjectReasoningEffort } from "../../db/database.js";
import { codexAppServer } from "../../codex/app-server-client.js";
import { execute, autocomplete } from "./model.js";

const catalog = {
  data: [
    { model: "model-a", displayName: "Model A", hidden: false, isDefault: true, defaultReasoningEffort: "medium", supportedReasoningEfforts: [{ reasoningEffort: "medium", description: "" }] },
    { model: "model-b", displayName: "Model B", hidden: false, isDefault: false, defaultReasoningEffort: "low", supportedReasoningEfforts: [{ reasoningEffort: "low", description: "" }] },
  ],
  nextCursor: null,
};

function command(value: string) {
  return {
    channelId: "ch1",
    options: { getString: vi.fn().mockReturnValue(value) },
    editReply: vi.fn().mockResolvedValue(undefined),
  };
}

describe("/model", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getProject).mockReturnValue({ model: "model-a" } as ReturnType<typeof getProject> & object);
    vi.mocked(codexAppServer.listModels).mockResolvedValue(catalog as Awaited<ReturnType<typeof codexAppServer.listModels>>);
  });

  it("resets model and reasoning without contacting Codex", async () => {
    const interaction = command("default");
    await execute(interaction as unknown as Parameters<typeof execute>[0]);
    expect(setProjectModel).toHaveBeenCalledWith("ch1", null);
    expect(setProjectReasoningEffort).toHaveBeenCalledWith("ch1", null);
    expect(codexAppServer.listModels).not.toHaveBeenCalled();
  });

  it("clears reasoning when switching models", async () => {
    await execute(command("model-b") as unknown as Parameters<typeof execute>[0]);
    expect(setProjectModel).toHaveBeenCalledWith("ch1", "model-b");
    expect(setProjectReasoningEffort).toHaveBeenCalledWith("ch1", null);
  });

  it("rejects unavailable models", async () => {
    const interaction = command("missing");
    await execute(interaction as unknown as Parameters<typeof execute>[0]);
    expect(setProjectModel).not.toHaveBeenCalled();
    expect(interaction.editReply).toHaveBeenCalledWith(expect.objectContaining({ content: expect.stringContaining("Unknown") }));
  });

  it("handles catalog errors", async () => {
    vi.mocked(codexAppServer.listModels).mockRejectedValueOnce(new Error("offline"));
    const interaction = command("model-b");
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      await execute(interaction as unknown as Parameters<typeof execute>[0]);
      expect(interaction.editReply).toHaveBeenCalledWith(expect.objectContaining({ content: expect.stringContaining("Could not retrieve") }));
    } finally {
      spy.mockRestore();
    }
  });

  it("provides autocomplete choices", async () => {
    const interaction = { options: { getFocused: () => "model" }, respond: vi.fn().mockResolvedValue(undefined) };
    await autocomplete(interaction as unknown as Parameters<typeof autocomplete>[0]);
    expect(interaction.respond).toHaveBeenCalledWith(expect.arrayContaining([{ name: "Model B", value: "model-b" }]));
  });
});

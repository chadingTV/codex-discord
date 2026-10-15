import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../db/database.js", () => ({
  getProject: vi.fn(),
  setProjectReasoningEffort: vi.fn(),
}));
vi.mock("../../codex/app-server-client.js", () => ({
  codexAppServer: { listModels: vi.fn() },
}));

import { getProject, setProjectReasoningEffort } from "../../db/database.js";
import { codexAppServer } from "../../codex/app-server-client.js";
import { execute, autocomplete } from "./reasoning.js";

const catalog = {
  data: [{
    model: "model-a", displayName: "Model A", hidden: false, isDefault: true,
    defaultReasoningEffort: "low",
    supportedReasoningEfforts: [
      { reasoningEffort: "low", description: "" },
      { reasoningEffort: "high", description: "" },
    ],
  }],
  nextCursor: null,
};

function command(value: string) {
  return {
    channelId: "ch1",
    options: { getString: vi.fn().mockReturnValue(value) },
    editReply: vi.fn().mockResolvedValue(undefined),
  };
}

describe("/reasoning", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getProject).mockReturnValue({ model: null } as ReturnType<typeof getProject> & object);
    vi.mocked(codexAppServer.listModels).mockResolvedValue(catalog as Awaited<ReturnType<typeof codexAppServer.listModels>>);
  });

  it("resets reasoning without contacting Codex", async () => {
    await execute(command("default") as unknown as Parameters<typeof execute>[0]);
    expect(setProjectReasoningEffort).toHaveBeenCalledWith("ch1", null);
    expect(codexAppServer.listModels).not.toHaveBeenCalled();
  });

  it("accepts a supported effort", async () => {
    await execute(command("high") as unknown as Parameters<typeof execute>[0]);
    expect(setProjectReasoningEffort).toHaveBeenCalledWith("ch1", "high");
  });

  it("rejects unsupported efforts", async () => {
    const interaction = command("ultra");
    await execute(interaction as unknown as Parameters<typeof execute>[0]);
    expect(setProjectReasoningEffort).not.toHaveBeenCalled();
    expect(interaction.editReply).toHaveBeenCalledWith(expect.objectContaining({ content: expect.stringContaining("not supported") }));
  });

  it("handles catalog errors in command execution", async () => {
    vi.mocked(codexAppServer.listModels).mockRejectedValueOnce(new Error("offline"));
    const interaction = command("high");
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      await execute(interaction as unknown as Parameters<typeof execute>[0]);
      expect(interaction.editReply).toHaveBeenCalledWith(expect.objectContaining({ content: expect.stringContaining("Could not retrieve") }));
    } finally {
      spy.mockRestore();
    }
  });

  it("handles autocomplete errors with an empty response", async () => {
    vi.mocked(codexAppServer.listModels).mockRejectedValueOnce(new Error("offline"));
    const interaction = {
      channelId: "ch1", options: { getFocused: () => "h" },
      respond: vi.fn().mockResolvedValue(undefined),
    };
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      await autocomplete(interaction as unknown as Parameters<typeof autocomplete>[0]);
      expect(interaction.respond).toHaveBeenCalledWith([]);
    } finally {
      spy.mockRestore();
    }
  });
});

import { randomUUID } from "node:crypto";
import type { MessageCreateOptions, TextChannel } from "discord.js";
import {
  upsertSession,
  updateSessionStatus,
  getProject,
  getSession,
  setAutoApprove,
} from "../db/database.js";
import { getConfig } from "../utils/config.js";
import { L } from "../utils/i18n.js";
import { codexAppServer } from "./app-server-client.js";
import {
  createAskUserQuestionEmbed,
  createCompletedButton,
  createResultEmbed,
  createStopButton,
  createToolApprovalEmbed,
  splitMessage,
} from "./output-formatter.js";

interface ActiveSession {
  channelId: string;
  channel: TextChannel;
  threadId: string;
  turnId: string | null;
  dbId: string;
}

interface QuestionPayload {
  id: string;
  header: string;
  question: string;
  options?: Array<{ label: string; description: string }>;
}

type ApprovalDecision = "accept" | "acceptForSession" | "decline" | "cancel";

type StreamMessage = Awaited<ReturnType<TextChannel["send"]>>;
type StreamState = {
  buffer: string;
  messages: StreamMessage[];
  lastEditTime: number;
  stopRow: ReturnType<typeof createStopButton>;
  startedAt: number;
  lastActivity: string;
  toolUseCount: number;
  heartbeat: NodeJS.Timeout;
  hasTextOutput: boolean;
  lastError: string | null;
};

const pendingApprovals = new Map<
  number,
  {
    resolve: (decision: ApprovalDecision) => void;
    channelId: string;
  }
>();

const pendingQuestions = new Map<
  number,
  {
    resolve: (answer: Record<string, { answers: string[] }>) => void;
    channelId: string;
    questionId: string;
  }
>();

const pendingCustomInputs = new Map<string, { requestId: number; questionId: string }>();

export class SessionManager {
  private sessions = new Map<string, ActiveSession>();
  private initialized = false;
  private static readonly MAX_QUEUE_SIZE = 5;
  private messageQueue = new Map<string, { channel: TextChannel; prompt: string }[]>();
  private pendingQueuePrompts = new Map<string, { channel: TextChannel; prompt: string }>();
  private streamState = new Map<string, StreamState>();

  private async ensureInitialized(): Promise<void> {
    if (this.initialized) return;

    await codexAppServer.ensureStarted();

    codexAppServer.on("notification", (msg) => {
      this.handleNotification(msg as { method: string; params?: Record<string, unknown> }).catch((error) => {
        console.error("Codex notification error:", error);
      });
    });

    codexAppServer.on("serverRequest", (msg) => {
      this.handleServerRequest(msg as { id: number; method: string; params: Record<string, unknown> }).catch((error) => {
        console.error("Codex server request error:", error);
      });
    });

    codexAppServer.on("stderr", (line) => {
      const text = String(line);
      if (!text.includes(" WARN ")) {
        console.warn("[codex]", text);
      }
    });

    this.initialized = true;
  }

  async sendMessage(channel: TextChannel, prompt: string): Promise<void> {
    await this.ensureInitialized();

    const channelId = channel.id;
    const project = getProject(channelId);
    if (!project) return;

    const existingSession = this.sessions.get(channelId);
    const dbSession = !existingSession ? getSession(channelId) : undefined;
    const dbId = existingSession?.dbId ?? dbSession?.id ?? randomUUID();
    let threadId = existingSession?.threadId ?? dbSession?.session_id ?? null;

    try {
      if (!threadId) {
        const thread = await codexAppServer.startThread(project.project_path);
        threadId = thread.id;
      } else if (!existingSession) {
        await codexAppServer.resumeThread(threadId);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to prepare Codex thread";
      const isResumeFailure = Boolean(threadId) && !existingSession;
      if (isResumeFailure) {
        console.error(`[codex] Failed to resume thread ${threadId} for channel ${channelId}:`, message);
        await channel.send(
          `❌ ${L("Failed to resume the selected Codex session", "선택한 Codex 세션을 재개하지 못했습니다")}: ${message}\n` +
          L(
            "Try `/sessions` again or choose `Create New Session`.",
            "`/sessions`를 다시 열거나 `새 세션 만들기`를 선택해 보세요."
          ),
        ).catch(() => {});
      } else {
        console.error(`[codex] Failed to start thread for channel ${channelId}:`, message);
        await channel.send(`❌ ${message}`).catch(() => {});
      }
      updateSessionStatus(channelId, "offline");
      this.finishSession(channelId);
      return;
    }

    upsertSession(dbId, channelId, threadId, "online");

    const stopRow = createStopButton(channelId);
    const currentMessage = await channel.send({
      content: L("⏳ Thinking...", "⏳ 생각 중..."),
      components: [stopRow],
    });

    const startedAt = Date.now();
    const heartbeat = setInterval(async () => {
      const stream = this.streamState.get(channelId);
      if (!stream || stream.hasTextOutput) return;
      const elapsed = Math.round((Date.now() - stream.startedAt) / 1000);
      try {
        await stream.messages.at(-1)?.edit({
          content: `⏳ ${stream.lastActivity} (${elapsed}s)`,
          components: [stream.stopRow],
        });
      } catch {
        // ignore
      }
    }, 15_000);

    this.streamState.set(channelId, {
      buffer: "",
      messages: [currentMessage],
      lastEditTime: 0,
      stopRow,
      startedAt,
      lastActivity: L("Thinking...", "생각 중..."),
      toolUseCount: 0,
      heartbeat,
      hasTextOutput: false,
      lastError: null,
    });

    this.sessions.set(channelId, {
      channelId,
      channel,
      threadId,
      turnId: null,
      dbId,
    });

    try {
      await codexAppServer.startTurn(threadId, prompt);
    } catch (error) {
      await channel.send(`❌ ${error instanceof Error ? error.message : "Failed to start Codex turn"}`);
      updateSessionStatus(channelId, "offline");
      this.finishSession(channelId);
    }
  }

  private async handleNotification(msg: { method: string; params?: Record<string, unknown> }): Promise<void> {
    const params = msg.params ?? {};
    const threadId = typeof params.threadId === "string" ? params.threadId : null;
    const active = threadId ? this.findActiveByThread(threadId) : undefined;
    if (!active) return;

    const channelId = active.channelId;
    const stream = this.streamState.get(channelId);

    switch (msg.method) {
      case "turn/started": {
        const turn = params.turn as { id?: string } | undefined;
        if (turn?.id) {
          active.turnId = turn.id;
          updateSessionStatus(channelId, "online");
        }
        return;
      }
      case "thread/status/changed": {
        const status = params.status as { type?: string; activeFlags?: string[] } | undefined;
        if (!status) return;
        if (status.type === "active") {
          const waiting =
            Array.isArray(status.activeFlags) &&
            status.activeFlags.some((flag) => flag === "waitingOnApproval" || flag === "waitingOnUserInput");
          updateSessionStatus(channelId, waiting ? "waiting" : "online");
        } else if (status.type === "idle") {
          updateSessionStatus(channelId, "idle");
        }
        return;
      }
      case "item/started": {
        if (!stream) return;
        const item = params.item as Record<string, unknown> | undefined;
        if (!item || typeof item.type !== "string") return;

        if (item.type !== "userMessage") {
          stream.toolUseCount++;
        }

        if (item.type === "commandExecution" && typeof item.command === "string") {
          const command = item.command.length > 80 ? item.command.slice(0, 80) + "…" : item.command;
          stream.lastActivity = `${L("Running command", "명령어 실행 중")} \`${command}\``;
        } else if (item.type === "fileChange") {
          stream.lastActivity = L("Editing files", "파일 편집 중");
        } else if (item.type === "webSearch") {
          stream.lastActivity = L("Searching web", "웹 검색 중");
        }

        if (!stream.hasTextOutput) {
          const elapsed = Math.round((Date.now() - stream.startedAt) / 1000);
          try {
            await stream.messages.at(-1)?.edit({
              content: `⏳ ${stream.lastActivity} (${elapsed}s) [${stream.toolUseCount} items]`,
              components: [stream.stopRow],
            });
          } catch {
            // ignore
          }
        }
        return;
      }
      case "item/agentMessage/delta": {
        if (!stream || typeof params.delta !== "string") return;
        stream.buffer += params.delta;
        stream.hasTextOutput = true;
        await this.flushStream(channelId);
        return;
      }
      case "error": {
        if (!stream) return;
        const error = params.error as { message?: string; additionalDetails?: string | null } | undefined;
        if (!error?.message) return;
        stream.lastError = error.additionalDetails
          ? `${error.message}\n${error.additionalDetails}`
          : error.message;
        return;
      }
      case "turn/completed": {
        const turn = params.turn as { status?: string | { type?: string }; error?: { message?: string; additionalDetails?: string | null } | null } | undefined;
        const statusType =
          typeof turn?.status === "string"
            ? turn.status
            : typeof turn?.status === "object" && turn.status
              ? turn.status.type
              : undefined;

        if (statusType === "failed") {
          const message =
            turn?.error?.additionalDetails
              ? `${turn.error.message ?? "Turn failed"}\n${turn.error.additionalDetails}`
              : turn?.error?.message ?? stream?.lastError ?? "Turn failed";
          if (stream) {
            await stream.messages.at(-1)?.edit({ content: `❌ ${message}`, components: [] }).catch(() => {});
          }
          updateSessionStatus(channelId, "offline");
          this.finishSession(channelId);
          return;
        }

        if (stream) {
          await this.flushStream(channelId, true);
          const durationMs = Date.now() - stream.startedAt;
          const payload: MessageCreateOptions = {
            embeds: [createResultEmbed(L("Task completed", "작업 완료"), 0, durationMs, getConfig().SHOW_COST)],
          };
          await active.channel.send(payload).catch(() => {});
        }

        updateSessionStatus(channelId, "idle");
        this.finishSession(channelId);
      }
    }
  }

  private async handleServerRequest(msg: { id: number; method: string; params: Record<string, unknown> }): Promise<void> {
    const threadId =
      typeof msg.params.threadId === "string"
        ? msg.params.threadId
        : typeof msg.params.conversationId === "string"
          ? msg.params.conversationId
          : null;
    const active = threadId ? this.findActiveByThread(threadId) : undefined;

    if (!active) {
      await codexAppServer.respond(msg.id, { decision: "decline" });
      return;
    }

    if (msg.method === "item/tool/requestUserInput") {
      const answers = await this.askUserInput(
        active.channel,
        active.channelId,
        msg.id,
        (msg.params.questions as QuestionPayload[]) ?? [],
      );
      await codexAppServer.respond(msg.id, { answers });
      return;
    }

    const project = getProject(active.channelId);
    if (project?.auto_approve) {
      await codexAppServer.respond(msg.id, { decision: "acceptForSession" });
      return;
    }

    const decision = await this.requestApproval(active.channel, active.channelId, msg.id, msg.method, msg.params);
    await codexAppServer.respond(msg.id, { decision });
  }

  private async requestApproval(
    channel: TextChannel,
    channelId: string,
    requestId: number,
    method: string,
    params: Record<string, unknown>,
  ): Promise<ApprovalDecision> {
    const toolName =
      method === "item/fileChange/requestApproval"
        ? "FileChange"
        : method === "item/commandExecution/requestApproval"
          ? "Bash"
          : "CodexAction";

    const input =
      method === "item/commandExecution/requestApproval"
        ? {
            command: typeof params.command === "string"
              ? params.command
              : Array.isArray(params.command)
                ? params.command.join(" ")
                : params.reason ?? "unknown",
            description: params.reason,
          }
        : params;

    const { embed, row } = createToolApprovalEmbed(toolName, input as Record<string, unknown>, String(requestId));
    updateSessionStatus(channelId, "waiting");
    await channel.send({ embeds: [embed], components: [row] });

    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        pendingApprovals.delete(requestId);
        updateSessionStatus(channelId, "online");
        resolve("cancel");
      }, 5 * 60 * 1000);

      pendingApprovals.set(requestId, {
        channelId,
        resolve: (decision) => {
          clearTimeout(timeout);
          pendingApprovals.delete(requestId);
          updateSessionStatus(channelId, "online");
          resolve(decision);
        },
      });
    });
  }

  private async askUserInput(
    channel: TextChannel,
    channelId: string,
    requestId: number,
    questions: QuestionPayload[],
  ): Promise<Record<string, { answers: string[] }>> {
    const answers: Record<string, { answers: string[] }> = {};

    for (let index = 0; index < questions.length; index++) {
      const question = questions[index];
      const { embed, components } = createAskUserQuestionEmbed(
        {
          header: question.header,
          question: question.question,
          options: question.options ?? [],
          multiSelect: false,
        },
        String(requestId),
        index,
        questions.length,
      );

      updateSessionStatus(channelId, "waiting");
      await channel.send({ embeds: [embed], components });

      const answer = await new Promise<Record<string, { answers: string[] }>>((resolve) => {
        const timeout = setTimeout(() => {
          pendingQuestions.delete(requestId);
          pendingCustomInputs.delete(channelId);
          resolve({ [question.id]: { answers: [] } });
        }, 5 * 60 * 1000);

        pendingQuestions.set(requestId, {
          channelId,
          questionId: question.id,
          resolve: (value) => {
            clearTimeout(timeout);
            pendingQuestions.delete(requestId);
            resolve(value);
          },
        });
      });

      answers[question.id] = answer[question.id] ?? { answers: [] };
    }

    updateSessionStatus(channelId, "online");
    return answers;
  }

  private async flushStream(channelId: string, final = false): Promise<void> {
    const stream = this.streamState.get(channelId);
    const active = this.sessions.get(channelId);
    if (!stream || !active || stream.buffer.length === 0) return;

    const now = Date.now();
    if (!final && now - stream.lastEditTime < 1500) return;
    stream.lastEditTime = now;

    const chunks = splitMessage(stream.buffer);
    try {
      for (let i = 0; i < chunks.length; i++) {
        const isLastChunk = i === chunks.length - 1;
        const payload = {
          content: chunks[i] || "...",
          components: isLastChunk
            ? final
              ? [createCompletedButton()]
              : [stream.stopRow]
            : [],
        };

        const existingMessage = stream.messages[i];
        if (existingMessage) {
          await existingMessage.edit(payload);
        } else {
          stream.messages.push(await active.channel.send(payload));
        }
      }
    } catch {
      // ignore
    }
  }

  private findActiveByThread(threadId: string): ActiveSession | undefined {
    return [...this.sessions.values()].find((entry) => entry.threadId === threadId);
  }

  async stopSession(channelId: string): Promise<boolean> {
    const session = this.sessions.get(channelId);
    if (!session || !session.turnId) return false;

    try {
      await codexAppServer.interruptTurn(session.threadId, session.turnId);
    } catch {
      // ignore
    }

    updateSessionStatus(channelId, "offline");
    this.finishSession(channelId);
    return true;
  }

  private finishSession(channelId: string): void {
    const stream = this.streamState.get(channelId);
    if (stream) {
      clearInterval(stream.heartbeat);
      this.streamState.delete(channelId);
    }

    this.sessions.delete(channelId);
    pendingCustomInputs.delete(channelId);

    const queue = this.messageQueue.get(channelId);
    if (queue && queue.length > 0) {
      const next = queue.shift()!;
      if (queue.length === 0) this.messageQueue.delete(channelId);
      const remaining = queue.length;
      const preview = next.prompt.length > 40 ? next.prompt.slice(0, 40) + "…" : next.prompt;
      const msg = remaining > 0
        ? L(`📨 Processing queued message... (remaining: ${remaining})\n> ${preview}`, `📨 대기 중이던 메시지를 처리합니다... (남은 큐: ${remaining}개)\n> ${preview}`)
        : L(`📨 Processing queued message...\n> ${preview}`, `📨 대기 중이던 메시지를 처리합니다...\n> ${preview}`);
      next.channel.send(msg).catch(() => {});
      this.sendMessage(next.channel, next.prompt).catch((err) => {
        console.error("Queue sendMessage error:", err);
      });
    }
  }

  isActive(channelId: string): boolean {
    return this.sessions.has(channelId);
  }

  resolveApproval(requestId: string, decision: "approve" | "deny" | "approve-all"): boolean {
    const id = Number(requestId);
    const pending = pendingApprovals.get(id);
    if (!pending) return false;

    if (decision === "approve-all") {
      setAutoApprove(pending.channelId, true);
      pending.resolve("acceptForSession");
    } else if (decision === "approve") {
      pending.resolve("accept");
    } else {
      pending.resolve("cancel");
    }

    return true;
  }

  resolveQuestion(requestId: string, answer: string): boolean {
    const id = Number(requestId);
    const pending = pendingQuestions.get(id);
    if (!pending) return false;
    pending.resolve({ [pending.questionId]: { answers: [answer] } });
    return true;
  }

  enableCustomInput(requestId: string, channelId: string, questionId = "answer"): void {
    pendingCustomInputs.set(channelId, { requestId: Number(requestId), questionId });
  }

  resolveCustomInput(channelId: string, text: string): boolean {
    const ci = pendingCustomInputs.get(channelId);
    if (!ci) return false;
    pendingCustomInputs.delete(channelId);

    const pending = pendingQuestions.get(ci.requestId);
    if (!pending) return false;
    pending.resolve({ [ci.questionId]: { answers: [text] } });
    return true;
  }

  hasPendingCustomInput(channelId: string): boolean {
    return pendingCustomInputs.has(channelId);
  }

  setPendingQueue(channelId: string, channel: TextChannel, prompt: string): void {
    this.pendingQueuePrompts.set(channelId, { channel, prompt });
  }

  confirmQueue(channelId: string): boolean {
    const pending = this.pendingQueuePrompts.get(channelId);
    if (!pending) return false;
    this.pendingQueuePrompts.delete(channelId);
    const queue = this.messageQueue.get(channelId) ?? [];
    queue.push(pending);
    this.messageQueue.set(channelId, queue);
    return true;
  }

  cancelQueue(channelId: string): void {
    this.pendingQueuePrompts.delete(channelId);
  }

  isQueueFull(channelId: string): boolean {
    const queue = this.messageQueue.get(channelId) ?? [];
    return queue.length >= SessionManager.MAX_QUEUE_SIZE;
  }

  hasQueue(channelId: string): boolean {
    return this.pendingQueuePrompts.has(channelId);
  }

  getQueueSize(channelId: string): number {
    return (this.messageQueue.get(channelId) ?? []).length;
  }

  getQueue(channelId: string): { channel: TextChannel; prompt: string }[] {
    return this.messageQueue.get(channelId) ?? [];
  }

  clearQueue(channelId: string): number {
    const queue = this.messageQueue.get(channelId) ?? [];
    const count = queue.length;
    this.messageQueue.delete(channelId);
    this.pendingQueuePrompts.delete(channelId);
    return count;
  }

  removeFromQueue(channelId: string, index: number): string | null {
    const queue = this.messageQueue.get(channelId) ?? [];
    if (index < 0 || index >= queue.length) return null;
    const [removed] = queue.splice(index, 1);
    if (queue.length === 0) this.messageQueue.delete(channelId);
    return removed.prompt;
  }
}

export const sessionManager = new SessionManager();

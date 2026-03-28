import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import { EventEmitter } from "node:events";

export interface CodexTurn {
  id: string;
  status: string | { type: string };
  error?: { message?: string; additionalDetails?: string | null } | null;
  items: CodexThreadItem[];
}

export type CodexThreadItem =
  | { type: "agentMessage"; id: string; text: string }
  | { type: "commandExecution"; id: string; command: string; cwd: string; status: string }
  | { type: "fileChange"; id: string; status: string; changes: Array<{ path: string; diff: string; kind: string }> }
  | { type: "userMessage"; id: string; content: unknown[] }
  | { type: string; id: string; [key: string]: unknown };

export interface CodexThreadSummary {
  id: string;
  preview: string;
  cwd: string;
  source: string;
  updatedAt: number;
  createdAt: number;
  modelProvider: string;
  path: string | null;
  name: string | null;
  status: unknown;
  turns: CodexTurn[];
}

export interface CodexRateLimitWindow {
  usedPercent: number;
  windowDurationMins?: number;
  resetsAt?: number;
}

export interface CodexRateLimitSnapshot {
  limitId?: string;
  limitName?: string;
  planType?: string;
  primary?: CodexRateLimitWindow;
  secondary?: CodexRateLimitWindow;
}

export interface CodexRateLimitsResponse {
  rateLimits: CodexRateLimitSnapshot;
  rateLimitsByLimitId?: Record<string, CodexRateLimitSnapshot>;
}

interface JsonRpcNotification {
  method: string;
  params?: Record<string, unknown>;
}

interface JsonRpcServerRequest {
  id: number;
  method: string;
  params: Record<string, unknown>;
}

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export class CodexAppServerClient extends EventEmitter {
  private process: ChildProcessWithoutNullStreams | null = null;
  private nextRequestId = 1;
  private pendingRequests = new Map<number, PendingRequest>();
  private initialized = false;
  private startPromise: Promise<void> | null = null;

  async ensureStarted(): Promise<void> {
    if (this.initialized) return;
    if (this.startPromise) return this.startPromise;

    this.startPromise = this.startInternal();
    try {
      await this.startPromise;
    } finally {
      this.startPromise = null;
    }
  }

  private async startInternal(): Promise<void> {
    this.process = spawn("codex", ["app-server"], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.process.once("exit", (code, signal) => {
      const reason = new Error(`Codex app-server exited (${code ?? "null"}${signal ? `, ${signal}` : ""})`);
      this.initialized = false;
      this.process = null;
      for (const [id, pending] of this.pendingRequests) {
        this.pendingRequests.delete(id);
        pending.reject(reason);
      }
      this.emit("exit", reason);
    });

    const stdout = createInterface({ input: this.process.stdout, crlfDelay: Infinity });
    stdout.on("line", (line) => this.handleStdoutLine(line));

    const stderr = createInterface({ input: this.process.stderr, crlfDelay: Infinity });
    stderr.on("line", (line) => {
      if (line.trim()) this.emit("stderr", line);
    });

    await this.requestWithProcess("initialize", {
      clientInfo: {
        name: "codex-discord",
        version: "0.1.0",
      },
      capabilities: {
        experimentalApi: true,
      },
    });

    this.initialized = true;
  }

  private handleStdoutLine(line: string): void {
    const trimmed = line.trim();
    if (!trimmed) return;

    let payload: unknown;
    try {
      payload = JSON.parse(trimmed);
    } catch {
      this.emit("stderr", `Non-JSON app-server output: ${trimmed}`);
      return;
    }

    if (!isObject(payload)) return;

    if ("id" in payload && "method" in payload && "params" in payload) {
      this.emit("serverRequest", payload as unknown as JsonRpcServerRequest);
      return;
    }

    if ("method" in payload) {
      this.emit("notification", payload as unknown as JsonRpcNotification);
      return;
    }

    if ("id" in payload && "result" in payload) {
      const id = Number(payload.id);
      const pending = this.pendingRequests.get(id);
      if (!pending) return;
      this.pendingRequests.delete(id);
      pending.resolve(payload.result);
      return;
    }

    if ("id" in payload && "error" in payload) {
      const id = Number(payload.id);
      const pending = this.pendingRequests.get(id);
      if (!pending) return;
      this.pendingRequests.delete(id);
      const errorMessage =
        isObject(payload.error) && typeof payload.error.message === "string"
          ? payload.error.message
          : "Unknown app-server error";
      pending.reject(new Error(errorMessage));
    }
  }

  private requestWithProcess<T = unknown>(method: string, params: Record<string, unknown>): Promise<T> {
    if (!this.process) throw new Error("Codex app-server is not running");

    const id = this.nextRequestId++;
    const response = new Promise<T>((resolve, reject) => {
      this.pendingRequests.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
      });
    });

    this.process.stdin.write(
      `${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`,
    );

    return response;
  }

  async request<T = unknown>(method: string, params: Record<string, unknown>): Promise<T> {
    await this.ensureStarted();
    return this.requestWithProcess<T>(method, params);
  }

  async respond(requestId: number, result: Record<string, unknown>): Promise<void> {
    await this.ensureStarted();
    if (!this.process) throw new Error("Codex app-server is not running");
    this.process.stdin.write(
      `${JSON.stringify({ jsonrpc: "2.0", id: requestId, result })}\n`,
    );
  }

  async listThreads(cwd: string): Promise<CodexThreadSummary[]> {
    const result = await this.request<{ data: CodexThreadSummary[] }>("thread/list", {
      cwd,
      sortKey: "updated_at",
      sourceKinds: ["vscode", "cli", "appServer", "exec"],
      limit: 100,
    });
    return result.data ?? [];
  }

  async readThread(threadId: string, includeTurns = false): Promise<CodexThreadSummary> {
    const result = await this.request<{ thread: CodexThreadSummary }>("thread/read", {
      threadId,
      includeTurns,
    });
    return result.thread;
  }

  async startThread(cwd: string): Promise<CodexThreadSummary> {
    const result = await this.request<{ thread: CodexThreadSummary }>("thread/start", {
      cwd,
      approvalPolicy: "on-request",
      sandbox: "workspace-write",
      modelProvider: "openai",
    });
    return result.thread;
  }

  async resumeThread(threadId: string): Promise<CodexThreadSummary> {
    const result = await this.request<{ thread: CodexThreadSummary }>("thread/resume", {
      threadId,
    });
    return result.thread;
  }

  async startTurn(threadId: string, prompt: string): Promise<{ id: string }> {
    const result = await this.request<{ turn: { id: string } }>("turn/start", {
      threadId,
      input: [{ type: "text", text: prompt }],
    });
    return result.turn;
  }

  async interruptTurn(threadId: string, turnId: string): Promise<void> {
    await this.request("turn/interrupt", { threadId, turnId });
  }

  async readRateLimits(): Promise<CodexRateLimitsResponse> {
    return this.request<CodexRateLimitsResponse>("account/rateLimits/read", {});
  }
}

export const codexAppServer = new CodexAppServerClient();

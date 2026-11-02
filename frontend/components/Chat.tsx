"use client";

import {
  Bot,
  PanelLeft,
  Send,
  Settings,
  Square,
} from "lucide-react";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import "highlight.js/styles/github-dark.css";
import CodeforcesStatsCard from "./CodeforcesStatsCard";
import ExecutionCard from "./ExecutionCard";
import MarkdownMessage from "./MarkdownMessage";
import RAGCitationBadge from "./RAGCitationBadge";
import SettingsModal from "./SettingsModal";
import Sidebar from "./Sidebar";
import ThemeToggle from "./ThemeToggle";
import LanguageToggle from "./LanguageToggle";
import {
  ProfileIncompleteError,
  assertOk,
  authFetch,
  createSession,
  listSessions,
  loadChatHistory,
  normalizeToolResult,
  type ChatMessage,
  type ChatSession,
  type ChatStreamEvent,
  type ToolChatMessage,
  type ToolName,
} from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

export default function Chat() {
  const { t, language } = useLanguage();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bootstrapped = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const hasInput = input.trim().length > 0;

  // Show the "thinking" animation while a response is in flight but nothing
  // visible is being produced: before the first token, and again between a
  // finished tool call and the model's next output. Running tools already
  // render their own loading cards.
  const lastMessage = messages[messages.length - 1];
  const showThinking =
    isStreaming &&
    (!lastMessage ||
      lastMessage.role === "user" ||
      (lastMessage.role === "assistant" && !lastMessage.content) ||
      (lastMessage.role === "tool" && lastMessage.status === "complete"));

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, showThinking]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  const hydrateSession = useCallback(async (id: string) => {
    setSessionId(id);
    setMessages([]);
    setBannerError(null);
    try {
      const history = await loadChatHistory(id);
      if (history.length > 0) setMessages(history);
    } catch (err) {
      setBannerError(
        t("chat.historyLoadError", { message: (err as Error).message }),
      );
    }
  }, [t]);

  const bootstrap = useCallback(async () => {
    setBannerError(null);
    try {
      const sessions = await listSessions();
      if (sessions.length > 0) {
        await hydrateSession(sessions[0].id);
        return;
      }
      const session = await createSession();
      await hydrateSession(session.id);
      setSidebarRefresh((n) => n + 1);
    } catch (err) {
      setBannerError(
        t("chat.sessionStartError", { message: (err as Error).message }),
      );
    }
  }, [hydrateSession, t]);

  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    bootstrap();
  }, [bootstrap]);

  async function handleRetry() {
    setIsRetrying(true);
    try {
      if (sessionId) {
        await hydrateSession(sessionId);
      } else {
        await bootstrap();
      }
    } finally {
      setIsRetrying(false);
    }
  }

  function handleSelectSession(id: string) {
    if (isStreaming || id === sessionId) return;
    hydrateSession(id);
  }

  function handleNewSession(session: ChatSession) {
    setMessages([]);
    setSessionId(session.id);
    setBannerError(null);
  }

  function handleSessionDeleted(deletedId: string) {
    if (sessionId !== deletedId) return;
    setSessionId(null);
    setMessages([]);
    setBannerError(null);
    void bootstrap();
  }

  function stopGenerating() {
    abortControllerRef.current?.abort();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || isStreaming || !sessionId) return;

    const streamMessagesRef: { current: ChatMessage[] } = {
      current: [
        ...messages,
        { role: "user", content: text },
        { role: "assistant", content: "" },
      ],
    };

    setMessages(streamMessagesRef.current);
    setInput("");
    setIsStreaming(true);

    const applyStreamMessages = (
      updater: (current: ChatMessage[]) => ChatMessage[],
    ) => {
      streamMessagesRef.current = updater(streamMessagesRef.current);
      setMessages([...streamMessagesRef.current]);
    };

    const appendTokenNow = (chunk: string) => {
      applyStreamMessages((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = {
            role: "assistant",
            content: last.content + chunk,
          };
          return next;
        }
        next.push({ role: "assistant", content: chunk });
        return next;
      });
    };

    // Streamed tokens are buffered and flushed at most once per animation
    // frame, so a fast stream doesn't trigger a React render (and a
    // markdown re-parse + scroll/layout) for every single token.
    let pendingText = "";
    let frameId: number | null = null;

    const flushTokens = () => {
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
        frameId = null;
      }
      if (!pendingText) return;
      const chunk = pendingText;
      pendingText = "";
      appendTokenNow(chunk);
    };

    const appendToken = (chunk: string) => {
      pendingText += chunk;
      if (frameId === null) {
        frameId = requestAnimationFrame(() => {
          frameId = null;
          flushTokens();
        });
      }
    };

    const appendToolLoading = (tool: ToolName) => {
      flushTokens();
      applyStreamMessages((current) => [
        ...current,
        { role: "tool", tool, status: "loading" } as ToolChatMessage,
      ]);
    };

    const completeToolExecution = <T extends ToolName>(
      tool: T,
      rawResult: unknown,
    ) => {
      flushTokens();
      const result = normalizeToolResult(tool, rawResult);
      if (!result) return;

      applyStreamMessages((current) => {
        const next = [...current];
        for (let i = next.length - 1; i >= 0; i -= 1) {
          const message = next[i];
          if (
            message.role === "tool" &&
            message.tool === tool &&
            message.status === "loading"
          ) {
            next[i] = {
              role: "tool",
              tool,
              status: "complete",
              result,
            } as ToolChatMessage;
            return next;
          }
        }
        next.push({
          role: "tool",
          tool,
          status: "complete",
          result,
        } as ToolChatMessage);
        return next;
      });
    };

    const handleStreamEvent = (event: ChatStreamEvent) => {
      switch (event.type) {
        case "token":
          appendToken(event.content);
          break;
        case "tool_start":
          appendToolLoading(event.name);
          break;
        case "tool_end":
          completeToolExecution(event.name, event.result);
          break;
      }
    };

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const res = await authFetch("/api/chat", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({
          message: text,
          thread_id: sessionId,
          language,
        }),
      });

      await assertOk(res);

      if (!res.body) {
        throw new Error("Empty response body");
      }

      await streamSseResponse(res.body, {
        signal: controller.signal,
        onEvent: handleStreamEvent,
        onDone: () => setIsStreaming(false),
      });
      setSidebarRefresh((n) => n + 1);
    } catch (err) {
      flushTokens();
      if (controller.signal.aborted) {
        applyStreamMessages((current) => {
          const next = [...current];
          const last = next[next.length - 1];
          if (last?.role === "assistant" && !last.content) {
            next.pop();
          }
          return next;
        });
        return;
      }
      if (err instanceof ProfileIncompleteError) {
        appendToken(err.message);
        setIsSettingsOpen(true);
      } else {
        appendToken(`Error: ${(err as Error).message}`);
      }
    } finally {
      flushTokens();
      abortControllerRef.current = null;
      setIsStreaming(false);
    }
  }

  return (
    <div className="fixed inset-0 flex overflow-hidden bg-white dark:bg-zinc-950">
      <Sidebar
        activeSessionId={sessionId}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onSessionDeleted={handleSessionDeleted}
        refreshToken={sidebarRefresh}
        disabled={isStreaming}
        mobileOpen={mobileSidebarOpen}
        onMobileClose={() => setMobileSidebarOpen(false)}
      />

      <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800 px-4 py-3 shrink-0">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setMobileSidebarOpen(true)}
              className="inline-flex items-center justify-center h-8 w-8 rounded-lg text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:bg-zinc-800 transition-all duration-150 lg:hidden"
              title={t("chat.openSidebar")}
              aria-label={t("chat.openSidebar")}
            >
              <PanelLeft className="h-5 w-5" />
            </button>
            <h1 className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              OCoach
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <LanguageToggle />
            <ThemeToggle />
            <button
              type="button"
              onClick={() => setIsSettingsOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 px-3 py-1.5 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-all duration-150"
            >
              <Settings className="h-4 w-4" />
              {t("chat.settings")}
            </button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-4">
          {bannerError && (
            <div className="flex items-center justify-between gap-3 mt-3 border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300 text-sm rounded-lg px-3 py-2">
              <span>{bannerError}</span>
              <button
                type="button"
                onClick={handleRetry}
                disabled={isRetrying}
                className="shrink-0 text-xs font-medium border border-red-300 dark:border-red-700 rounded-md px-2 py-1 hover:bg-red-100 dark:hover:bg-red-900/30 disabled:opacity-50 transition-all duration-150"
              >
                {isRetrying ? t("chat.retrying") : t("chat.retry")}
              </button>
            </div>
          )}

          <div
            ref={scrollRef}
            className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-y-contain py-4"
          >
            {messages.length === 0 && (
              <p className="text-sm text-zinc-500 dark:text-zinc-400 text-center mt-8">
                {t("chat.emptyState")}
              </p>
            )}
            {messages.map((m, i) => (
              <MessageRow key={i} message={m} />
            ))}
            {showThinking && <ThinkingIndicator label={t("chat.thinking")} />}
          </div>

          <div className="shrink-0 pb-4 pt-2">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void sendMessage();
              }}
            >
              <div className="relative flex items-end rounded-2xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-sm focus-within:shadow-md focus-within:border-zinc-400 dark:focus-within:border-zinc-500 transition-all duration-150">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={t("chat.placeholder")}
                  disabled={!sessionId || isStreaming}
                  rows={1}
                  className="flex-1 resize-none bg-transparent px-4 py-3 pr-12 text-sm text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 focus:outline-none disabled:opacity-50 max-h-40"
                />
                {isStreaming ? (
                  <button
                    type="button"
                    onClick={stopGenerating}
                    className="absolute right-2 bottom-2 inline-flex items-center justify-center h-8 w-8 rounded-lg text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30 transition-all duration-150"
                    title={t("chat.stopGenerating")}
                    aria-label={t("chat.stopGenerating")}
                  >
                    <Square className="h-4 w-4 fill-current" />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!sessionId || !hasInput}
                    className={`absolute right-2 bottom-2 inline-flex items-center justify-center h-8 w-8 rounded-lg transition-all duration-150 ${
                      hasInput
                        ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-200"
                        : "text-zinc-300 dark:text-zinc-600 cursor-not-allowed"
                    }`}
                    title={t("chat.sendMessage")}
                    aria-label={t("chat.sendMessage")}
                  >
                    <Send className="h-4 w-4" />
                  </button>
                )}
              </div>
              <p className="mt-1.5 text-center text-[11px] text-zinc-400 dark:text-zinc-500">
                {t("chat.enterToSend")}
              </p>
            </form>
          </div>
        </div>
      </div>

      {isSettingsOpen && (
        <SettingsModal
          onClose={() => setIsSettingsOpen(false)}
          onSaved={() => setSidebarRefresh((n) => n + 1)}
        />
      )}
    </div>
  );
}

// Memoized so that during streaming only the message that actually changed
// re-renders. `applyStreamMessages` replaces just the touched message object,
// so unchanged messages keep their identity and skip re-rendering — which
// avoids re-parsing/highlighting earlier markdown replies and re-laying-out
// a very large user prompt on every streamed token.
const MessageRow = memo(function MessageRow({
  message: m,
}: {
  message: ChatMessage;
}) {
  if (m.role === "tool") {
    return (
      <div className="self-start max-w-[90%] w-full">
        {m.tool === "compile_and_test_cpp" && (
          <ExecutionCard loading={m.status === "loading"} result={m.result} />
        )}
        {m.tool === "get_user_stats" && (
          <CodeforcesStatsCard
            kind="stats"
            loading={m.status === "loading"}
            result={m.result}
          />
        )}
        {m.tool === "get_upcoming_contests" && (
          <CodeforcesStatsCard
            kind="contests"
            loading={m.status === "loading"}
            result={m.result}
          />
        )}
        {m.tool === "search_cp_knowledge" && (
          <RAGCitationBadge
            loading={m.status === "loading"}
            result={m.result}
          />
        )}
      </div>
    );
  }

  if (m.role === "assistant" && !m.content) {
    return null;
  }

  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 px-4 py-2.5">
          <p className="text-sm whitespace-pre-wrap break-words">{m.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 max-w-[90%]">
      <div className="shrink-0 flex items-start pt-1">
        <div className="flex items-center justify-center h-7 w-7 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
          <Bot className="h-4 w-4" />
        </div>
      </div>
      <div className="min-w-0 text-zinc-900 dark:text-zinc-100">
        <MarkdownMessage content={m.content} />
      </div>
    </div>
  );
});

function ThinkingIndicator({ label }: { label: string }) {
  return (
    <div
      className="flex gap-3 max-w-[90%]"
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      <div className="shrink-0 flex items-start pt-1">
        <div className="flex items-center justify-center h-7 w-7 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
          <Bot className="h-4 w-4 animate-pulse" />
        </div>
      </div>
      <div className="flex items-center gap-2 py-1.5 text-sm text-zinc-500 dark:text-zinc-400">
        <span className="animate-pulse">{label}</span>
        <span className="flex items-center gap-1" aria-hidden="true">
          {[0, 150, 300].map((delay) => (
            <span
              key={delay}
              className="h-1.5 w-1.5 rounded-full bg-zinc-400 dark:bg-zinc-500 animate-bounce"
              style={{ animationDelay: `${delay}ms` }}
            />
          ))}
        </span>
      </div>
    </div>
  );
}

type SseHandlers = {
  signal?: AbortSignal;
  onEvent: (event: ChatStreamEvent) => void;
  onDone: () => void;
};

function parseStreamEvent(data: string): ChatStreamEvent | null {
  try {
    const parsed = JSON.parse(data) as ChatStreamEvent;
    if (parsed && typeof parsed === "object" && "type" in parsed) {
      return parsed;
    }
  } catch {
    // Legacy plain-text token frames fall through below.
  }
  return null;
}

async function streamSseResponse(
  body: ReadableStream<Uint8Array>,
  { signal, onEvent, onDone }: SseHandlers,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = false;

  const onAbort = () => {
    done = true;
    void reader.cancel().catch(() => {});
  };

  signal?.addEventListener("abort", onAbort, { once: true });

  try {
    while (!done) {
      if (signal?.aborted) break;

      const { value, done: readerDone } = await reader.read();
      if (readerDone) break;

      buffer += decoder.decode(value, { stream: true });

      let separatorIndex: number;
      while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
        const rawFrame = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        const dataLines = rawFrame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice("data:".length).replace(/^ /, ""));
        if (dataLines.length === 0) continue;

        const data = dataLines.join("\n");
        if (data === "[DONE]") {
          done = true;
          break;
        }

        const event = parseStreamEvent(data);
        if (event) {
          onEvent(event);
        } else {
          onEvent({ type: "token", content: data });
        }
      }
    }
  } finally {
    signal?.removeEventListener("abort", onAbort);
    onDone();
    await reader.cancel().catch(() => {});
  }
}

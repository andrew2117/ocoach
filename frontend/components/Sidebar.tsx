"use client";

import { PanelLeftClose, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createSession,
  deleteSession,
  listSessions,
  updateSession,
  type ChatSession,
} from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

type SidebarProps = {
  activeSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewSession: (session: ChatSession) => void;
  onSessionDeleted?: (sessionId: string) => void;
  refreshToken?: number;
  disabled?: boolean;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
};

type SessionGroup = {
  label: string;
  sessions: ChatSession[];
};

type DateGroupKey =
  | "sidebar.groups.today"
  | "sidebar.groups.yesterday"
  | "sidebar.groups.previous7Days"
  | "sidebar.groups.older";

function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

function groupSessionsByDate(sessions: ChatSession[]): Record<DateGroupKey, ChatSession[]> {
  const now = new Date();
  const today = startOfDay(now);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);

  const buckets: Record<DateGroupKey, ChatSession[]> = {
    "sidebar.groups.today": [],
    "sidebar.groups.yesterday": [],
    "sidebar.groups.previous7Days": [],
    "sidebar.groups.older": [],
  };

  for (const session of sessions) {
    const created = new Date(session.created_at);
    const day = startOfDay(created);
    if (day.getTime() === today.getTime()) {
      buckets["sidebar.groups.today"].push(session);
    } else if (day.getTime() === yesterday.getTime()) {
      buckets["sidebar.groups.yesterday"].push(session);
    } else if (day >= weekAgo) {
      buckets["sidebar.groups.previous7Days"].push(session);
    } else {
      buckets["sidebar.groups.older"].push(session);
    }
  }

  return buckets;
}

export default function Sidebar({
  activeSessionId,
  onSelectSession,
  onNewSession,
  onSessionDeleted,
  refreshToken = 0,
  disabled = false,
  mobileOpen = false,
  onMobileClose,
}: SidebarProps) {
  const { t } = useLanguage();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionSessionId, setActionSessionId] = useState<string | null>(null);
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(
    null,
  );
  const [renameDraft, setRenameDraft] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const renameRowRef = useRef<HTMLLIElement>(null);

  const defaultChatTitle = t("sidebar.defaultChatTitle");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listSessions();
      setSessions(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, refreshToken]);

  const groups = useMemo((): SessionGroup[] => {
    const buckets = groupSessionsByDate(sessions);
    return (Object.entries(buckets) as [DateGroupKey, ChatSession[]][])
      .filter(([, items]) => items.length > 0)
      .map(([key, items]) => ({ label: t(key), sessions: items }));
  }, [sessions, t]);

  async function handleNewChat() {
    if (disabled) return;
    try {
      const session = await createSession();
      setSessions((prev) => [session, ...prev]);
      onNewSession(session);
      onMobileClose?.();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function startRename(session: ChatSession) {
    if (disabled) return;
    setConfirmDeleteId(null);
    setRenamingSessionId(session.id);
    setRenameDraft(session.title || defaultChatTitle);
    setError(null);
  }

  function cancelRename() {
    setRenamingSessionId(null);
    setRenameDraft("");
  }

  const commitRename = useCallback(async (session: ChatSession) => {
    const trimmed = renameDraft.trim();
    if (!trimmed) {
      setError(t("sidebar.titleEmpty"));
      return;
    }
    if (trimmed === (session.title || defaultChatTitle)) {
      cancelRename();
      return;
    }

    const previousTitle = session.title;
    setActionSessionId(session.id);
    setError(null);
    setSessions((prev) =>
      prev.map((item) =>
        item.id === session.id ? { ...item, title: trimmed } : item,
      ),
    );
    cancelRename();

    try {
      const updated = await updateSession(session.id, trimmed);
      setSessions((prev) =>
        prev.map((item) => (item.id === session.id ? updated : item)),
      );
    } catch (err) {
      setSessions((prev) =>
        prev.map((item) =>
          item.id === session.id ? { ...item, title: previousTitle } : item,
        ),
      );
      setError((err as Error).message);
    } finally {
      setActionSessionId(null);
    }
  }, [renameDraft, defaultChatTitle, t]);

  useEffect(() => {
    if (!renamingSessionId) return;

    function handlePointerDown(event: MouseEvent) {
      if (
        renameRowRef.current &&
        !renameRowRef.current.contains(event.target as Node)
      ) {
        const session = sessions.find((s) => s.id === renamingSessionId);
        if (session) void commitRename(session);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [renamingSessionId, sessions, commitRename]);

  function requestDelete(session: ChatSession) {
    if (disabled) return;
    setConfirmDeleteId(session.id);
    cancelRename();
  }

  function cancelDelete() {
    setConfirmDeleteId(null);
  }

  async function confirmDelete(session: ChatSession) {
    setActionSessionId(session.id);
    setError(null);
    setConfirmDeleteId(null);

    const previousSessions = sessions;
    setSessions((prev) => prev.filter((item) => item.id !== session.id));
    onSessionDeleted?.(session.id);

    try {
      await deleteSession(session.id);
    } catch (err) {
      setSessions(previousSessions);
      setError((err as Error).message);
    } finally {
      setActionSessionId(null);
    }
  }

  const asideClasses = [
    "flex flex-col border-r border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 shrink-0",
    "w-64 h-full",
    "fixed inset-y-0 left-0 z-40 transition-transform duration-150 lg:relative lg:translate-x-0",
    mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
  ].join(" ");

  return (
    <>
      {mobileOpen && (
        <button
          type="button"
          aria-label={t("sidebar.closeSidebar")}
          className="fixed inset-0 z-30 bg-black/20 lg:hidden"
          onClick={onMobileClose}
        />
      )}

      <aside className={asideClasses}>
        <div className="flex items-center justify-between px-3 py-3 border-b border-zinc-200 dark:border-zinc-800">
          <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            {t("sidebar.title")}
          </span>
          {onMobileClose && (
            <button
              type="button"
              onClick={onMobileClose}
              className="inline-flex items-center justify-center h-7 w-7 rounded-md text-zinc-500 hover:text-zinc-900 hover:bg-zinc-200/60 dark:hover:text-zinc-100 dark:hover:bg-zinc-800 transition-all duration-150 lg:hidden"
              title={t("sidebar.closeSidebar")}
              aria-label={t("sidebar.closeSidebar")}
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          )}
        </div>

        <div className="p-3">
          <button
            type="button"
            onClick={handleNewChat}
            disabled={disabled}
            className="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-50 transition-all duration-150"
          >
            <Plus className="h-4 w-4" />
            {t("sidebar.newChat")}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-2 pb-3">
          {loading && (
            <p className="text-xs text-zinc-500 px-2 py-2">
              {t("sidebar.loadingSessions")}
            </p>
          )}
          {error && (
            <p className="text-xs text-red-600 dark:text-red-400 px-2 py-2">
              {error}
            </p>
          )}
          {!loading && !error && groups.length === 0 && (
            <p className="text-xs text-zinc-500 px-2 py-2">
              {t("sidebar.noChatsYet")}
            </p>
          )}
          {groups.map((group) => (
            <div key={group.label} className="mb-3">
              <p className="text-[11px] uppercase tracking-wide text-zinc-500 dark:text-zinc-400 px-2 mb-1.5 font-medium">
                {group.label}
              </p>
              <ul className="flex flex-col gap-0.5">
                {group.sessions.map((session) => {
                  const active = session.id === activeSessionId;
                  const busy = actionSessionId === session.id;
                  const isRenaming = renamingSessionId === session.id;
                  const isConfirmingDelete = confirmDeleteId === session.id;
                  const sessionTitle = session.title || defaultChatTitle;

                  if (isRenaming) {
                    return (
                      <li
                        key={session.id}
                        ref={renameRowRef}
                        className="flex items-center gap-1 px-1"
                      >
                        <input
                          value={renameDraft}
                          onChange={(e) => setRenameDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              void commitRename(session);
                            }
                            if (e.key === "Escape") cancelRename();
                          }}
                          autoFocus
                          className="flex-1 min-w-0 text-sm rounded-md border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-900 px-2 py-1.5 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-400 dark:focus:ring-zinc-500 transition-all duration-150"
                        />
                      </li>
                    );
                  }

                  if (isConfirmingDelete) {
                    return (
                      <li
                        key={session.id}
                        className="flex items-center gap-2 rounded-lg px-2 py-1.5 bg-red-50 dark:bg-red-950/30"
                      >
                        <span className="flex-1 min-w-0 text-xs text-red-700 dark:text-red-300 truncate">
                          {t("sidebar.deleteConfirm", { title: sessionTitle })}
                        </span>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => confirmDelete(session)}
                          className="shrink-0 text-xs font-medium px-2 py-1 rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-all duration-150"
                        >
                          {t("sidebar.confirm")}
                        </button>
                        <button
                          type="button"
                          onClick={cancelDelete}
                          className="shrink-0 text-xs font-medium px-2 py-1 rounded-md text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200/60 dark:hover:bg-zinc-800 transition-all duration-150"
                        >
                          {t("sidebar.cancel")}
                        </button>
                      </li>
                    );
                  }

                  return (
                    <li
                      key={session.id}
                      className="group flex items-stretch gap-0.5 px-1"
                    >
                      <button
                        type="button"
                        disabled={disabled || busy}
                        onClick={() => {
                          onSelectSession(session.id);
                          onMobileClose?.();
                        }}
                        className={`flex-1 min-w-0 text-left text-sm rounded-lg px-2.5 py-2 truncate disabled:opacity-50 transition-all duration-150 ${
                          active
                            ? "bg-zinc-200/80 dark:bg-zinc-800/60 text-zinc-900 dark:text-zinc-100 font-medium"
                            : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200/50 dark:hover:bg-zinc-800/40"
                        }`}
                      >
                        {sessionTitle}
                      </button>
                      <div
                        className={`shrink-0 flex items-center gap-0.5 transition-opacity duration-150 ${
                          busy
                            ? "opacity-100"
                            : "opacity-0 group-hover:opacity-100 focus-within:opacity-100"
                        }`}
                      >
                        <button
                          type="button"
                          disabled={disabled || busy}
                          onClick={() => startRename(session)}
                          title={t("sidebar.rename")}
                          aria-label={t("sidebar.renameChat")}
                          className="inline-flex items-center justify-center h-8 w-7 rounded-md text-zinc-500 hover:text-zinc-900 hover:bg-zinc-200/60 dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50 transition-all duration-150"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          disabled={disabled || busy}
                          onClick={() => requestDelete(session)}
                          title={t("sidebar.delete")}
                          aria-label={t("sidebar.deleteChat")}
                          className="inline-flex items-center justify-center h-8 w-7 rounded-md text-zinc-500 hover:text-red-600 hover:bg-red-50 dark:text-zinc-400 dark:hover:text-red-400 dark:hover:bg-red-950/30 disabled:opacity-50 transition-all duration-150"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}

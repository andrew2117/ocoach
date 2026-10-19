import { createClient } from "@/lib/supabase/client";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ProfileIncompleteError extends Error {
  readonly message: string;

  constructor(message: string) {
    super(message);
    this.name = "ProfileIncompleteError";
    this.message = message;
  }
}

/**
 * Thrown by {@link loadChatHistory} on any non-OK response or malformed
 * body, instead of the previous behavior of swallowing the failure and
 * returning `[]` (indistinguishable from "this thread has no messages
 * yet"). Callers (see `components/Chat.tsx`) catch this to render a
 * visible error state with a retry action rather than silently showing an
 * empty chat.
 */
export class ChatHistoryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChatHistoryError";
  }
}

export async function getAccessToken(): Promise<string> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  if (!token) {
    throw new Error("No active session token found");
  }
  return token;
}

export async function authFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await getAccessToken();

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(`${API_URL}${path}`, { ...init, headers });
}

type ApiErrorBody = {
  detail?: string | { error?: string; message?: string };
};

export async function readApiError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail.message === "string") return detail.message;
  } catch {
    // Response body wasn't JSON — fall through to status text.
  }
  return res.statusText || `Request failed (${res.status})`;
}

export async function assertOk(res: Response): Promise<void> {
  if (res.ok) return;

  if (res.status === 403) {
    try {
      const body = (await res.clone().json()) as ApiErrorBody;
      const detail = body.detail;
      if (
        typeof detail === "object" &&
        detail?.error === "profile_incomplete"
      ) {
        throw new ProfileIncompleteError(
          detail.message ??
            "Configure your Anthropic API key in Settings before chatting.",
        );
      }
    } catch (err) {
      if (err instanceof ProfileIncompleteError) throw err;
    }
  }

  throw new Error(await readApiError(res));
}

export type ChatSession = {
  id: string;
  title: string;
  created_at: string;
  updated_at?: string;
};

export type CppExecutionVerdict =
  | "success"
  | "ce"
  | "wa"
  | "tle"
  | "re"
  | "error";

export type CppExecutionResult = {
  status: string;
  stdout: string | null;
  stderr: string | null;
  compile_output: string | null;
  time: number | null;
  memory: number | null;
  verdict: CppExecutionVerdict;
};

// Phase 10: Codeforces profile/weakness stats, surfaced by `get_user_stats`
// via CodeforcesStatsCard.tsx.
export type CodeforcesWeakTag = {
  tag: string;
  count: number;
};

export type CodeforcesStatsResult = {
  handle: string;
  rating: number | null;
  max_rating: number | null;
  rank: string | null;
  max_rank: string | null;
  submissions_analyzed: number;
  weak_tags: CodeforcesWeakTag[];
  error: string | null;
};

// Phase 10: upcoming Codeforces contest schedule, surfaced by
// `get_upcoming_contests` via CodeforcesStatsCard.tsx.
export type CodeforcesContest = {
  id: number | null;
  name: string;
  start_time_iso: string | null;
  duration_hours: number;
};

export type CodeforcesContestsResult = {
  contests: CodeforcesContest[];
  error: string | null;
};

// Phase 10: Qdrant knowledge-base citations, surfaced by
// `search_cp_knowledge` via RAGCitationBadge.tsx.
export type RagCitationChunk = {
  source: string;
  topic: string;
  snippet: string;
  score: number | null;
};

export type RagCitationsResult = {
  query: string;
  chunks: RagCitationChunk[];
  error: string | null;
};

export type UserChatMessage = {
  role: "user";
  content: string;
};

export type AssistantChatMessage = {
  role: "assistant";
  content: string;
};

export type ToolName =
  | "compile_and_test_cpp"
  | "search_cp_knowledge"
  | "get_user_stats"
  | "get_upcoming_contests";

/** Maps each streamed tool name to its normalized frontend result shape. */
export type ToolResultMap = {
  compile_and_test_cpp: CppExecutionResult;
  search_cp_knowledge: RagCitationsResult;
  get_user_stats: CodeforcesStatsResult;
  get_upcoming_contests: CodeforcesContestsResult;
};

export type ToolChatMessage = {
  [T in ToolName]: {
    role: "tool";
    tool: T;
    status: "loading" | "complete";
    result?: ToolResultMap[T];
  };
}[ToolName];

export type ChatMessage =
  | UserChatMessage
  | AssistantChatMessage
  | ToolChatMessage;

export type ChatStreamEvent =
  | { type: "token"; content: string }
  | { type: "tool_start"; name: ToolName }
  | {
      [T in ToolName]: { type: "tool_end"; name: T; result: ToolResultMap[T] };
    }[ToolName];

function inferVerdict(status: string): CppExecutionVerdict {
  const normalized = status.toLowerCase();
  if (normalized.includes("compilation")) return "ce";
  if (normalized.includes("time limit")) return "tle";
  if (status === "Accepted") return "success";
  if (normalized.includes("wrong answer")) return "wa";
  if (normalized.includes("runtime") || normalized.startsWith("killed")) {
    return "re";
  }
  return "error";
}

export function normalizeCppExecutionResult(
  raw: Partial<CppExecutionResult> | null | undefined,
): CppExecutionResult | null {
  if (!raw || typeof raw.status !== "string") return null;

  const verdict =
    raw.verdict && typeof raw.verdict === "string"
      ? (raw.verdict as CppExecutionVerdict)
      : inferVerdict(raw.status);

  return {
    status: raw.status,
    stdout: raw.stdout ?? null,
    stderr: raw.stderr ?? null,
    compile_output: raw.compile_output ?? null,
    time: typeof raw.time === "number" ? raw.time : null,
    memory: typeof raw.memory === "number" ? raw.memory : null,
    verdict,
  };
}

export function normalizeCodeforcesStatsResult(
  raw: Partial<CodeforcesStatsResult> | null | undefined,
): CodeforcesStatsResult | null {
  if (!raw || typeof raw.handle !== "string") return null;

  return {
    handle: raw.handle,
    rating: typeof raw.rating === "number" ? raw.rating : null,
    max_rating: typeof raw.max_rating === "number" ? raw.max_rating : null,
    rank: typeof raw.rank === "string" ? raw.rank : null,
    max_rank: typeof raw.max_rank === "string" ? raw.max_rank : null,
    submissions_analyzed:
      typeof raw.submissions_analyzed === "number"
        ? raw.submissions_analyzed
        : 0,
    weak_tags: Array.isArray(raw.weak_tags)
      ? raw.weak_tags.filter(
          (t): t is CodeforcesWeakTag =>
            !!t && typeof t.tag === "string" && typeof t.count === "number",
        )
      : [],
    error: typeof raw.error === "string" ? raw.error : null,
  };
}

export function normalizeCodeforcesContestsResult(
  raw: Partial<CodeforcesContestsResult> | null | undefined,
): CodeforcesContestsResult | null {
  if (!raw) return null;

  return {
    contests: Array.isArray(raw.contests)
      ? raw.contests
          .filter(
            (c): c is CodeforcesContest => !!c && typeof c.name === "string",
          )
          .map((c) => ({
            id: typeof c.id === "number" ? c.id : null,
            name: c.name,
            start_time_iso:
              typeof c.start_time_iso === "string" ? c.start_time_iso : null,
            duration_hours:
              typeof c.duration_hours === "number" ? c.duration_hours : 0,
          }))
      : [],
    error: typeof raw.error === "string" ? raw.error : null,
  };
}

export function normalizeRagCitationsResult(
  raw: Partial<RagCitationsResult> | null | undefined,
): RagCitationsResult | null {
  if (!raw) return null;

  return {
    query: typeof raw.query === "string" ? raw.query : "",
    chunks: Array.isArray(raw.chunks)
      ? raw.chunks
          .filter(
            (c): c is RagCitationChunk => !!c && typeof c.snippet === "string",
          )
          .map((c) => ({
            source: typeof c.source === "string" ? c.source : "unknown",
            topic: typeof c.topic === "string" ? c.topic : "",
            snippet: c.snippet,
            score: typeof c.score === "number" ? c.score : null,
          }))
      : [],
    error: typeof raw.error === "string" ? raw.error : null,
  };
}

/** Dispatches to the right normalizer for a streamed tool's raw result. */
export function normalizeToolResult<T extends ToolName>(
  tool: T,
  raw: unknown,
): ToolResultMap[T] | null {
  switch (tool) {
    case "compile_and_test_cpp":
      return normalizeCppExecutionResult(
        raw as Partial<CppExecutionResult>,
      ) as ToolResultMap[T] | null;
    case "search_cp_knowledge":
      return normalizeRagCitationsResult(
        raw as Partial<RagCitationsResult>,
      ) as ToolResultMap[T] | null;
    case "get_user_stats":
      return normalizeCodeforcesStatsResult(
        raw as Partial<CodeforcesStatsResult>,
      ) as ToolResultMap[T] | null;
    case "get_upcoming_contests":
      return normalizeCodeforcesContestsResult(
        raw as Partial<CodeforcesContestsResult>,
      ) as ToolResultMap[T] | null;
    default:
      return null;
  }
}

export type ModelOptionResponse = {
  id: string;
  provider: "anthropic" | "openai" | "google";
  label: string;
};

/**
 * Phase 11: multi-provider BYOK. One `has_*`/`*_preview` pair per provider,
 * plus the user's selected `default_model` and the full catalog
 * (`available_models`, mirroring `backend/agent/models.py::MODEL_CATALOG`)
 * so the Settings dropdown doesn't need its own hardcoded id list.
 */
export type UserProfile = {
  codeforces_handle: string | null;
  default_model: string;
  available_models: ModelOptionResponse[];

  has_anthropic_api_key: boolean;
  /**
   * Masked preview of the stored Anthropic key (e.g. `"sk-ant-***abcd"`),
   * or `null` if none is stored. Never the raw decrypted secret — see
   * `backend/routes/profile.py::_mask_api_key`. Safe to render directly.
   */
  anthropic_api_key_preview: string | null;

  has_openai_api_key: boolean;
  /** Masked preview of the stored OpenAI key, or `null` if none is stored. */
  openai_api_key_preview: string | null;

  has_google_api_key: boolean;
  /** Masked preview of the stored Google (Gemini) key, or `null` if none is stored. */
  google_api_key_preview: string | null;
};

/**
 * Fetches the caller's profile from the backend (`GET /api/profile`).
 *
 * Phase 7: this replaces the previous direct-to-Supabase read from
 * `SettingsModal.tsx` — `public.profiles` no longer grants `authenticated`
 * any privileges at all (see the Phase 7 RLS-lockdown migration), so this
 * backend-fronted read (service role, masked preview only) is now the
 * only way the frontend can learn profile state.
 */
export async function getProfile(): Promise<UserProfile> {
  const res = await authFetch("/api/profile");
  await assertOk(res);
  return res.json();
}

/**
 * Saves profile changes (`POST /api/profile`). Every field is optional —
 * omitting (or passing `null` for) a provider key leaves that provider's
 * previously-saved key untouched server-side (see
 * `backend/services/profiles.py::upsert_profile`), so callers only need to
 * send the field(s) the user actually changed. `codeforces_handle` is the
 * one exception: it's always overwritten (including to clear it).
 */
export async function saveProfile(payload: {
  codeforces_handle: string | null;
  anthropic_api_key?: string | null;
  openai_api_key?: string | null;
  google_api_key?: string | null;
  default_model?: string | null;
}): Promise<UserProfile> {
  const res = await authFetch("/api/profile", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  await assertOk(res);
  return res.json();
}

export async function listSessions(): Promise<ChatSession[]> {
  const res = await authFetch("/api/sessions");
  await assertOk(res);
  return res.json();
}

export async function createSession(title?: string): Promise<ChatSession> {
  const res = await authFetch("/api/sessions", {
    method: "POST",
    body: JSON.stringify(title ? { title } : {}),
  });
  await assertOk(res);
  return res.json();
}

export async function updateSession(
  sessionId: string,
  title: string,
): Promise<ChatSession> {
  const res = await authFetch(
    `/api/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ title }),
    },
  );
  await assertOk(res);
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await authFetch(
    `/api/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
  await assertOk(res);
}

/**
 * Loads a thread's prior messages for the message-log UI.
 *
 * Throws {@link ChatHistoryError} on any non-OK response (including a 403
 * from the backend's fail-closed thread-ownership check — see
 * `backend/routes/chat.py::_authorize_thread`) or a malformed body,
 * instead of the previous behavior of swallowing the failure into `[]`.
 * Callers must catch this and surface it — an empty array here used to be
 * ambiguous between "new thread, no messages yet" and "history fetch
 * failed"; it no longer is.
 */
export async function loadChatHistory(
  sessionId: string,
): Promise<ChatMessage[]> {
  const res = await authFetch(
    `/api/chat/history/${encodeURIComponent(sessionId)}`,
  );
  if (!res.ok) {
    throw new ChatHistoryError(await readApiError(res));
  }
  const data = await res.json();
  if (!Array.isArray(data.messages)) {
    throw new ChatHistoryError("Malformed chat history response from server");
  }
  return data.messages;
}

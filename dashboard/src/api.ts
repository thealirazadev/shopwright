const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const KEY = "shopwright.merchantToken";

export class AuthError extends Error {}

export function savedToken(): string {
  try {
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(KEY, token);
    else sessionStorage.removeItem(KEY);
  } catch {
    // Storage blocked: the token lives only for this page load.
  }
}

export async function api<T>(token: string, path: string, method = "GET"): Promise<T> {
  const response = await fetch(BASE + path, {
    method,
    headers: { Authorization: `Bearer ${token}` },
  });
  if (response.status === 401) throw new AuthError("Your session has expired. Sign in again.");
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export interface Conversation {
  id: string;
  status: "open" | "handoff";
  handoff_reason: string | null;
  created_at: string;
  updated_at: string;
  messages: number;
}

export interface TraceEvent {
  turn: number;
  kind: string;
  name: string;
  detail: unknown;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
}

export interface Timeline extends Omit<Conversation, "messages" | "updated_at"> {
  messages: { role: "user" | "assistant"; content: unknown; created_at: string }[];
  events: TraceEvent[];
}

export interface Proposal {
  id: string;
  conversation_id: string;
  kind: string;
  order_ref: string;
  reason: string;
  policy_sources: unknown;
  status: string;
  execution_error: string | null;
  created_at: string;
}

export interface DayCost {
  day: string;
  conversations: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
}

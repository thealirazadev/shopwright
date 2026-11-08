import { useCallback, useState } from "react";
import { api, type Conversation, type Timeline } from "./api";
import { Empty, ErrorLine, useLoad, when } from "./ui";

interface Props {
  token: string;
  onError: (e: unknown) => void;
  status?: "handoff";
}

export function Conversations({ token, onError, status }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  const query = status ? `?status=${status}` : "";
  const load = useCallback(
    () => api<Conversation[]>(token, `/v1/admin/conversations${query}`),
    [token, query],
  );
  const { data, error } = useLoad(load, onError);

  if (open) return <TimelineView token={token} id={open} onError={onError} back={() => setOpen(null)} />;
  return (
    <section>
      <ErrorLine message={error} />
      {data?.length === 0 && (
        <Empty>{status ? "No conversations are waiting for a person." : "No conversations yet."}</Empty>
      )}
      <ul className="divide-y divide-neutral-200 rounded-lg border border-neutral-200 bg-white">
        {data?.map((c) => (
          <li key={c.id}>
            <button
              className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left hover:bg-neutral-50"
              onClick={() => setOpen(c.id)}
            >
              <span className="min-w-0">
                <span className="block truncate font-mono text-xs text-neutral-500">{c.id}</span>
                <span className="text-sm">
                  {c.messages} messages
                  {c.handoff_reason && <span className="text-amber-700"> · {c.handoff_reason}</span>}
                </span>
              </span>
              <span className="shrink-0 text-xs text-neutral-500">{when(c.updated_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function messageText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((block: { type?: string; text?: string; name?: string }) =>
        block.type === "text" ? block.text : block.type === "tool_use" ? `[calls ${block.name}]` : "",
      )
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

function TimelineView({
  token,
  id,
  onError,
  back,
}: {
  token: string;
  id: string;
  onError: (e: unknown) => void;
  back: () => void;
}) {
  const load = useCallback(() => api<Timeline>(token, `/v1/admin/conversations/${id}`), [token, id]);
  const { data, error } = useLoad(load, onError);
  const tokens = data?.events.reduce((n, e) => n + e.input_tokens + e.output_tokens, 0) ?? 0;

  return (
    <section className="space-y-4">
      <button className="text-sm text-neutral-600 hover:underline" onClick={back}>
        ← All conversations
      </button>
      <ErrorLine message={error} />
      {data && (
        <>
          <p className="text-sm text-neutral-600">
            Started {when(data.created_at)} · {data.events.length} trace events · {tokens} tokens
            {data.status === "handoff" && <span className="text-amber-700"> · handed off</span>}
          </p>
          <ol className="space-y-2">
            {data.messages
              .map((m) => ({ ...m, text: messageText(m.content) }))
              .filter((m) => m.text)
              .map((m, i) => (
                <li
                  key={i}
                  className={`max-w-prose whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                    m.role === "user" ? "ml-auto bg-neutral-900 text-white" : "bg-white ring-1 ring-neutral-200"
                  }`}
                >
                  {m.text}
                </li>
              ))}
          </ol>
          <h2 className="pt-2 text-sm font-semibold">Trace</h2>
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-neutral-500">
              <tr>
                <th className="py-1">Turn</th>
                <th>Step</th>
                <th className="text-right">Latency</th>
                <th className="text-right">Tokens in / out</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200">
              {data.events.map((e, i) => (
                <tr key={i}>
                  <td className="py-1">{e.turn}</td>
                  <td>
                    <span className="text-neutral-500">{e.kind}</span> {e.name}
                  </td>
                  <td className="text-right tabular-nums">{e.latency_ms} ms</td>
                  <td className="text-right tabular-nums">
                    {e.input_tokens} / {e.output_tokens}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

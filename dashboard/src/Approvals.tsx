import { useCallback, useState } from "react";
import { api, type Proposal } from "./api";
import { Empty, ErrorLine, useLoad, when } from "./ui";

const OUTCOME: Record<string, string> = {
  executed: "Approved and done in Shopify.",
  approved: "Approved. Complete it in Shopify admin.",
  failed: "Approved, but Shopify refused it. See the error below.",
  rejected: "Rejected.",
};

export function Approvals({ token, onError }: { token: string; onError: (e: unknown) => void }) {
  const load = useCallback(() => api<Proposal[]>(token, "/v1/admin/proposals"), [token]);
  const { data, error, reload } = useLoad(load, onError);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  async function decide(p: Proposal, decision: "approve" | "reject") {
    // One request in flight per proposal; the API also refuses a second decision (409).
    setBusy(p.id);
    setMessage("");
    try {
      const result = await api<{ status: string }>(
        token,
        `/v1/admin/proposals/${p.id}/${decision}`,
        "POST",
      );
      setMessage(`Order ${p.order_ref}: ${OUTCOME[result.status] ?? result.status}`);
    } catch (e) {
      onError(e);
      setMessage(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(null);
      reload();
    }
  }

  return (
    <section className="space-y-3">
      <ErrorLine message={error} />
      {message && <p className="rounded-md bg-white px-3 py-2 text-sm ring-1 ring-neutral-200">{message}</p>}
      {data?.length === 0 && <Empty>Nothing is waiting for approval.</Empty>}
      {data?.map((p) => (
        <article key={p.id} className="rounded-lg border border-neutral-200 bg-white p-4">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-medium capitalize">
              {p.kind} order {p.order_ref}
            </h2>
            <span className="text-xs text-neutral-500">{when(p.created_at)}</span>
          </div>
          <p className="mt-1 text-sm text-neutral-700">{p.reason}</p>
          {p.execution_error && <p className="mt-1 text-sm text-red-700">{p.execution_error}</p>}
          <div className="mt-3 flex gap-2">
            <button
              className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              disabled={busy === p.id}
              onClick={() => decide(p, "approve")}
            >
              Approve
            </button>
            <button
              className="rounded-md px-3 py-1.5 text-sm ring-1 ring-neutral-300 disabled:opacity-50"
              disabled={busy === p.id}
              onClick={() => decide(p, "reject")}
            >
              Reject
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}

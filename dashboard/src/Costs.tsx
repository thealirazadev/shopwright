import { useCallback } from "react";
import { api, type DayCost } from "./api";
import { Empty, ErrorLine, useLoad } from "./ui";

export function Costs({ token, onError }: { token: string; onError: (e: unknown) => void }) {
  const load = useCallback(() => api<DayCost[]>(token, "/v1/admin/costs?days=30"), [token]);
  const { data, error } = useLoad(load, onError);
  const rows = data ?? [];
  const total = rows.reduce((n, d) => n + Number(d.cost_usd), 0);
  const tokens = rows.reduce((n, d) => n + d.input_tokens + d.output_tokens, 0);
  const peak = Math.max(1, ...rows.map((d) => d.input_tokens + d.output_tokens));
  const priced = rows.some((d) => Number(d.cost_usd) > 0);

  return (
    <section className="space-y-4">
      <ErrorLine message={error} />
      <div className="grid grid-cols-2 gap-3">
        <Stat label="Model cost, last 30 days" value={priced ? "$" + total.toFixed(2) : "Not priced"} />
        <Stat label="Tokens, last 30 days" value={tokens.toLocaleString()} />
      </div>
      {!priced && rows.length > 0 && (
        <p className="text-sm text-neutral-600">
          Set AGENT_INPUT_USD_PER_MTOK and AGENT_OUTPUT_USD_PER_MTOK on the API to see cost.
        </p>
      )}
      {data && rows.length === 0 && <Empty>No model usage in the last 30 days.</Empty>}
      {rows.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-neutral-500">
            <tr>
              <th className="py-1">Day</th>
              <th className="text-right">Conversations</th>
              <th className="w-1/3 pl-4">Tokens</th>
              <th className="text-right">Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-200">
            {rows.map((d) => {
              const used = d.input_tokens + d.output_tokens;
              return (
                <tr key={d.day}>
                  <td className="py-1 tabular-nums">{d.day}</td>
                  <td className="text-right tabular-nums">{d.conversations}</td>
                  <td className="pl-4">
                    <div className="flex items-center gap-2">
                      <div
                        className="h-2 rounded-sm bg-neutral-800"
                        style={{ width: Math.max(2, (used / peak) * 100) + "%" }}
                      />
                      <span className="text-xs tabular-nums text-neutral-500">{used.toLocaleString()}</span>
                    </div>
                  </td>
                  <td className="text-right tabular-nums">{"$" + d.cost_usd}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <p className="text-xs text-neutral-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

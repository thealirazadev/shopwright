import { useCallback, useState } from "react";
import { AuthError, saveToken, savedToken } from "./api";
import { Approvals } from "./Approvals";
import { Conversations } from "./Conversations";

const TABS = ["Approvals", "Handoffs", "Conversations"] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const [token, setToken] = useState(savedToken);
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState<Tab>("Approvals");

  const signOut = useCallback((message = "") => {
    saveToken("");
    setToken("");
    setNotice(message);
  }, []);
  const onError = useCallback(
    (e: unknown) => {
      if (e instanceof AuthError) signOut(e.message);
    },
    [signOut],
  );

  if (!token) {
    return (
      <SignIn
        notice={notice}
        onSubmit={(t) => {
          saveToken(t);
          setToken(t);
        }}
      />
    );
  }
  return (
    <main className="mx-auto min-h-screen max-w-4xl bg-neutral-50 px-4 py-6 text-neutral-900">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Shopwright</h1>
        <button className="text-sm text-neutral-600 hover:underline" onClick={() => signOut()}>
          Sign out
        </button>
      </header>
      <nav className="mb-4 flex gap-1 border-b border-neutral-200">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              tab === t ? "border-neutral-900 font-medium" : "border-transparent text-neutral-500"
            }`}
          >
            {t}
          </button>
        ))}
      </nav>
      {tab === "Approvals" && <Approvals token={token} onError={onError} />}
      {tab === "Handoffs" && <Conversations token={token} onError={onError} status="handoff" />}
      {tab === "Conversations" && <Conversations token={token} onError={onError} />}
    </main>
  );
}

function SignIn({ notice, onSubmit }: { notice: string; onSubmit: (token: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <main className="grid min-h-screen place-items-center bg-neutral-50 px-4 text-neutral-900">
      <form
        className="w-full max-w-sm space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim()) onSubmit(value.trim());
        }}
      >
        <h1 className="text-xl font-semibold tracking-tight">Shopwright</h1>
        <p className="text-sm text-neutral-600">
          Paste the merchant token issued with <code>python -m app.dashboard.token</code>.
        </p>
        {notice && <p className="text-sm text-amber-700">{notice}</p>}
        <input
          className="w-full rounded-md border border-neutral-300 px-3 py-2 font-mono text-xs"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label="Merchant token"
          autoFocus
        />
        <button className="w-full rounded-md bg-neutral-900 px-3 py-2 text-sm text-white">Sign in</button>
      </form>
    </main>
  );
}

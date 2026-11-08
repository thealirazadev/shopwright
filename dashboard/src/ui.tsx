import { useCallback, useEffect, useState } from "react";

export function useLoad<T>(load: () => Promise<T>, onError: (e: unknown) => void) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    setError("");
    load()
      .then(setData)
      .catch((e: unknown) => {
        onError(e);
        setError(e instanceof Error ? e.message : "Something went wrong");
      });
  }, [load, onError]);
  useEffect(reload, [reload]);
  return { data, error, reload };
}

export function when(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-8 text-center text-sm text-neutral-500">{children}</p>;
}

export function ErrorLine({ message }: { message: string }) {
  return message ? <p className="py-2 text-sm text-red-700">{message}</p> : null;
}

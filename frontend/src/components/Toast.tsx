import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Msg = { id: number; text: string; err?: boolean };
const Ctx = createContext<(text: string, err?: boolean) => void>(() => {});
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const push = useCallback((text: string, err = false) => {
    const id = ++seq;
    setMsgs((m) => [...m, { id, text, err }]);
    setTimeout(() => setMsgs((m) => m.filter((x) => x.id !== id)), err ? 8000 : 4000);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toast" role="status">
        {msgs.map((m) => (
          <div key={m.id} className={m.err ? "err" : ""}>{m.text}</div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

/** toast("Kaydedildi") or toast(error.message, true) */
export const useToast = () => useContext(Ctx);

export function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

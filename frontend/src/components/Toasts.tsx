import { useToasts } from "../store/toasts";

export function Toasts() {
  const items = useToasts((s) => s.items);
  const remove = useToasts((s) => s.remove);
  if (items.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {items.map((t) => (
        <div
          key={t.id}
          role="alert"
          className={`rounded-lg shadow-lg px-4 py-3 text-sm text-white cursor-pointer ${
            t.kind === "error"
              ? "bg-red-600"
              : t.kind === "success"
              ? "bg-green-600"
              : "bg-slate-700"
          }`}
          onClick={() => remove(t.id)}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}

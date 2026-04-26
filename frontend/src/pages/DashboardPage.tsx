import { useAuthStore } from "../store/auth";
import { useJobEvents } from "../hooks/useJobEvents";
import { JobForm } from "../components/JobForm";
import { JobList } from "../components/JobList";

export function DashboardPage() {
  const token = useAuthStore((s) => s.token);
  const username = useAuthStore((s) => s.username);
  const logout = useAuthStore((s) => s.logout);

  useJobEvents(token);

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <h1 className="text-lg font-semibold">Prosperas Reports</h1>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-500">@{username}</span>
            <button
              onClick={logout}
              className="text-slate-600 hover:text-slate-900 underline-offset-2 hover:underline"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <section className="max-w-5xl mx-auto px-4 py-6">
        <JobForm />
        <JobList />
      </section>
    </main>
  );
}

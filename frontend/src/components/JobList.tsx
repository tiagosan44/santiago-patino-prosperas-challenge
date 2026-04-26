import { useEffect } from "react";

import { getJob } from "../api/jobs";
import { useAuthStore } from "../store/auth";
import { useJobsStore, useSortedJobs } from "../store/jobs";
import { useToasts } from "../store/toasts";
import { StatusBadge } from "./StatusBadge";

export function JobList() {
  const token = useAuthStore((s) => s.token);
  const loadJobs = useJobsStore((s) => s.loadJobs);
  const loadMore = useJobsStore((s) => s.loadMore);
  const isLoading = useJobsStore((s) => s.isLoading);
  const cursor = useJobsStore((s) => s.cursor);
  const jobs = useSortedJobs();
  const pushToast = useToasts((s) => s.push);

  useEffect(() => {
    if (token) loadJobs(token);
  }, [token, loadJobs]);

  const handleDownload = async (jobId: string) => {
    if (!token) return;
    try {
      // Re-fetch to get a fresh presigned URL
      const fresh = await getJob(jobId, token);
      if (fresh.result_url) {
        window.open(fresh.result_url, "_blank", "noopener,noreferrer");
      } else {
        pushToast("error", "No result URL yet");
      }
    } catch (e) {
      pushToast("error", e instanceof Error ? e.message : "download failed");
    }
  };

  if (jobs.length === 0 && isLoading) {
    return <p className="text-slate-500 italic mt-6">Loading reports…</p>;
  }
  if (jobs.length === 0) {
    return <p className="text-slate-500 italic mt-6">No reports yet — queue one above.</p>;
  }

  return (
    <div className="mt-6 space-y-3">
      {/* Desktop table */}
      <div className="hidden md:block bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left text-slate-600">
            <tr>
              <th className="px-4 py-2">Report</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Created</th>
              <th className="px-4 py-2">Attempts</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {jobs.map((j) => (
              <tr key={j.job_id}>
                <td className="px-4 py-2 font-mono text-xs">
                  <div>{j.report_type}</div>
                  <div className="text-slate-400">{j.job_id.slice(0, 8)}…</div>
                </td>
                <td className="px-4 py-2">
                  <StatusBadge status={j.status} />
                  {j.status === "FAILED" && j.error && (
                    <div className="text-xs text-red-600 mt-1" title={j.error}>
                      {j.error.length > 60 ? `${j.error.slice(0, 60)}…` : j.error}
                    </div>
                  )}
                </td>
                <td className="px-4 py-2 text-slate-500 text-xs">
                  {new Date(j.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-2 text-slate-500">{j.attempts}</td>
                <td className="px-4 py-2 text-right">
                  {j.status === "COMPLETED" && (
                    <button
                      type="button"
                      onClick={() => handleDownload(j.job_id)}
                      className="px-2.5 py-1 bg-slate-900 text-white rounded text-xs hover:bg-slate-700"
                    >
                      Download
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="md:hidden space-y-2">
        {jobs.map((j) => (
          <div key={j.job_id} className="bg-white rounded-lg shadow p-4 text-sm">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-medium">{j.report_type}</div>
                <div className="text-xs text-slate-400 font-mono">{j.job_id.slice(0, 8)}…</div>
              </div>
              <StatusBadge status={j.status} />
            </div>
            <div className="text-xs text-slate-500 mt-2">
              {new Date(j.created_at).toLocaleString()}
              {" · "}
              attempts: {j.attempts}
            </div>
            {j.status === "FAILED" && j.error && (
              <div className="text-xs text-red-600 mt-2">{j.error}</div>
            )}
            {j.status === "COMPLETED" && (
              <button
                type="button"
                onClick={() => handleDownload(j.job_id)}
                className="mt-3 w-full px-3 py-1.5 bg-slate-900 text-white rounded text-xs"
              >
                Download
              </button>
            )}
          </div>
        ))}
      </div>

      {cursor && (
        <div className="flex justify-center mt-4">
          <button
            type="button"
            onClick={() => token && loadMore(token)}
            disabled={isLoading}
            className="px-4 py-2 text-sm border border-slate-300 rounded-md hover:bg-white disabled:opacity-60"
          >
            {isLoading ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}

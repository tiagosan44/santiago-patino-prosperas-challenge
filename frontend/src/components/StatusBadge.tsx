import type { JobStatus } from "../api/jobs";

const STYLES: Record<JobStatus, { bg: string; label: string; pulse?: boolean }> = {
  PENDING: { bg: "bg-status-pending", label: "Pending", pulse: true },
  PROCESSING: { bg: "bg-status-processing", label: "Processing", pulse: true },
  COMPLETED: { bg: "bg-status-completed", label: "Completed" },
  FAILED: { bg: "bg-status-failed", label: "Failed" },
};

export function StatusBadge({ status }: { status: JobStatus }) {
  const cfg = STYLES[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium text-white ${cfg.bg}`}
    >
      {cfg.pulse && (
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-60" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-white" />
        </span>
      )}
      {cfg.label}
    </span>
  );
}

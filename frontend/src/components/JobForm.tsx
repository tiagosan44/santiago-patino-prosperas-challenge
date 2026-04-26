import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { useAuthStore } from "../store/auth";
import { useJobsStore } from "../store/jobs";
import { useToasts } from "../store/toasts";

const REPORT_TYPES = [
  { value: "sales", label: "Sales" },
  { value: "inventory", label: "Inventory" },
  { value: "users", label: "Users" },
  { value: "audit", label: "Audit (high priority)" },
  { value: "executive_summary", label: "Executive summary (high priority)" },
  { value: "force_failure", label: "Force failure (demo)" },
];

const FORMATS = ["json", "csv", "pdf"] as const;

const Schema = z.object({
  report_type: z.string().min(1, "select a report type"),
  date_range: z.string().optional().or(z.literal("")),
  format: z.enum(FORMATS),
});

type FormData = z.infer<typeof Schema>;

export function JobForm() {
  const token = useAuthStore((s) => s.token);
  const createJob = useJobsStore((s) => s.createJob);
  const pushToast = useToasts((s) => s.push);

  const { register, handleSubmit, reset, formState } = useForm<FormData>({
    resolver: zodResolver(Schema),
    defaultValues: { report_type: "sales", date_range: "", format: "json" },
  });

  const onSubmit = async (data: FormData) => {
    if (!token) {
      pushToast("error", "Not authenticated");
      return;
    }
    try {
      await createJob(
        {
          report_type: data.report_type,
          date_range: data.date_range || null,
          format: data.format,
        },
        token
      );
      pushToast("success", "Report queued");
      reset({ report_type: data.report_type, date_range: "", format: "json" });
    } catch (e) {
      pushToast("error", e instanceof Error ? e.message : "could not create report");
    }
  };

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      className="bg-white rounded-lg shadow p-6 grid gap-4 sm:grid-cols-3"
    >
      <div className="sm:col-span-1">
        <label className="block text-sm font-medium mb-1" htmlFor="report_type">
          Report type
        </label>
        <select
          id="report_type"
          {...register("report_type")}
          className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
        >
          {REPORT_TYPES.map((rt) => (
            <option key={rt.value} value={rt.value}>
              {rt.label}
            </option>
          ))}
        </select>
        {formState.errors.report_type && (
          <p className="text-xs text-red-600 mt-1">{formState.errors.report_type.message}</p>
        )}
      </div>

      <div className="sm:col-span-1">
        <label className="block text-sm font-medium mb-1" htmlFor="date_range">
          Date range (optional)
        </label>
        <input
          id="date_range"
          type="text"
          placeholder="2026-01-01..2026-04-26"
          {...register("date_range")}
          className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
        />
      </div>

      <div className="sm:col-span-1">
        <label className="block text-sm font-medium mb-1" htmlFor="format">
          Format
        </label>
        <select
          id="format"
          {...register("format")}
          className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
        >
          {FORMATS.map((f) => (
            <option key={f} value={f}>
              {f.toUpperCase()}
            </option>
          ))}
        </select>
      </div>

      <div className="sm:col-span-3 flex justify-end">
        <button
          type="submit"
          disabled={formState.isSubmitting}
          className="px-4 py-2 bg-slate-900 text-white rounded-md text-sm hover:bg-slate-700 disabled:opacity-60"
        >
          {formState.isSubmitting ? "Queueing…" : "Generate report"}
        </button>
      </div>
    </form>
  );
}

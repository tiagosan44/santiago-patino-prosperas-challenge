import { apiRequest } from "./client";

export type JobStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export interface Job {
  job_id: string;
  user_id: string;
  status: JobStatus;
  report_type: string;
  priority: "high" | "standard";
  result_url: string | null;
  error: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
}

export interface JobPage {
  items: Job[];
  next_cursor: string | null;
}

export interface CreateJobRequest {
  report_type: string;
  date_range?: string | null;
  format: "json" | "csv" | "pdf";
}

export function createJob(payload: CreateJobRequest, token: string): Promise<Job> {
  return apiRequest<Job>("/jobs", {
    method: "POST",
    body: payload,
    token,
  });
}

export function listJobs(token: string, cursor?: string, limit = 20): Promise<JobPage> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (cursor) params.set("cursor", cursor);
  return apiRequest<JobPage>(`/jobs?${params.toString()}`, { token });
}

export function getJob(jobId: string, token: string): Promise<Job> {
  return apiRequest<Job>(`/jobs/${encodeURIComponent(jobId)}`, { token });
}

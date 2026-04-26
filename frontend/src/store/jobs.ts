import { create } from "zustand";

import * as jobsApi from "../api/jobs";
import type { Job, JobStatus } from "../api/jobs";

interface JobsState {
  byId: Record<string, Job>;
  cursor: string | null;
  isLoading: boolean;
  loadError: string | null;

  // Selectors derive lists; expose helpers for components.
  loadJobs: (token: string) => Promise<void>;
  loadMore: (token: string) => Promise<void>;
  createJob: (req: jobsApi.CreateJobRequest, token: string) => Promise<Job>;
  applyEvent: (event: { job_id: string; status: JobStatus; result_url?: string | null; error?: string | null; updated_at?: string }) => void;
  reset: () => void;
}

function listSorted(byId: Record<string, Job>): Job[] {
  return Object.values(byId).sort(
    (a, b) => b.created_at.localeCompare(a.created_at)
  );
}

export const useJobsStore = create<JobsState>((set, get) => ({
  byId: {},
  cursor: null,
  isLoading: false,
  loadError: null,

  async loadJobs(token) {
    set({ isLoading: true, loadError: null });
    try {
      const page = await jobsApi.listJobs(token);
      const next: Record<string, Job> = {};
      for (const j of page.items) next[j.job_id] = j;
      set({ byId: next, cursor: page.next_cursor, isLoading: false });
    } catch (e) {
      set({
        loadError: e instanceof Error ? e.message : "failed to load jobs",
        isLoading: false,
      });
    }
  },

  async loadMore(token) {
    const cursor = get().cursor;
    if (!cursor) return;
    set({ isLoading: true });
    try {
      const page = await jobsApi.listJobs(token, cursor);
      set((s) => {
        const merged = { ...s.byId };
        for (const j of page.items) merged[j.job_id] = j;
        return { byId: merged, cursor: page.next_cursor, isLoading: false };
      });
    } catch (e) {
      set({
        loadError: e instanceof Error ? e.message : "failed to load more",
        isLoading: false,
      });
    }
  },

  async createJob(req, token) {
    const job = await jobsApi.createJob(req, token);
    set((s) => ({ byId: { ...s.byId, [job.job_id]: job } }));
    return job;
  },

  applyEvent(event) {
    set((s) => {
      const existing = s.byId[event.job_id];
      if (!existing) return s; // event for a job we haven't loaded — ignored
      return {
        byId: {
          ...s.byId,
          [event.job_id]: {
            ...existing,
            status: event.status,
            result_url: event.result_url ?? existing.result_url,
            error: event.error ?? existing.error,
            updated_at: event.updated_at ?? existing.updated_at,
          },
        },
      };
    });
  },

  reset() {
    set({ byId: {}, cursor: null, isLoading: false, loadError: null });
  },
}));

export function useSortedJobs(): Job[] {
  return useJobsStore((s) => listSorted(s.byId));
}

import { describe, it, expect, vi, beforeEach } from "vitest";

import { useJobsStore } from "../src/store/jobs";
import type { Job } from "../src/api/jobs";

const mkJob = (id: string, status: Job["status"] = "PENDING"): Job => ({
  job_id: id,
  user_id: "u-1",
  status,
  report_type: "sales",
  priority: "standard",
  result_url: null,
  error: null,
  attempts: 0,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
});

describe("useJobsStore", () => {
  beforeEach(() => {
    useJobsStore.getState().reset();
    vi.restoreAllMocks();
  });

  it("loadJobs populates byId from API response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            items: [mkJob("a"), mkJob("b")],
            next_cursor: "C",
          }),
          { status: 200 }
        )
      )
    );

    await useJobsStore.getState().loadJobs("tok");

    const s = useJobsStore.getState();
    expect(Object.keys(s.byId)).toHaveLength(2);
    expect(s.cursor).toBe("C");
  });

  it("applyEvent updates an existing job's status", () => {
    const existing = mkJob("a", "PENDING");
    useJobsStore.setState({ byId: { a: existing } });

    useJobsStore.getState().applyEvent({
      job_id: "a",
      status: "PROCESSING",
      updated_at: "2026-04-26T00:00:00Z",
    });

    expect(useJobsStore.getState().byId["a"].status).toBe("PROCESSING");
  });

  it("applyEvent ignores events for unknown jobs", () => {
    useJobsStore.getState().applyEvent({
      job_id: "ghost",
      status: "COMPLETED",
    });
    expect(useJobsStore.getState().byId["ghost"]).toBeUndefined();
  });
});

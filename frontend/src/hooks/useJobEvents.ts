import { useEffect } from "react";

import { getApiBaseUrl } from "../api/client";
import { useJobsStore } from "../store/jobs";
import { useToasts } from "../store/toasts";

/**
 * Subscribes to GET /events/me?token=<jwt> and routes 'job-update'
 * events into the jobs store. EventSource cannot send custom HTTP
 * headers, so the JWT travels via query string. The browser handles
 * automatic reconnect with backoff.
 */
export function useJobEvents(token: string | null) {
  const applyEvent = useJobsStore((s) => s.applyEvent);
  const pushToast = useToasts((s) => s.push);

  useEffect(() => {
    if (!token) return;
    const url = `${getApiBaseUrl()}/events/me?token=${encodeURIComponent(token)}`;
    const source = new EventSource(url);

    const handle = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        applyEvent(data);
        if (data.status === "COMPLETED") {
          pushToast("success", `Report ${shortId(data.job_id)} completed`);
        } else if (data.status === "FAILED") {
          pushToast("error", `Report ${shortId(data.job_id)} failed`);
        }
      } catch (_err) {
        // ignore malformed events; the browser auto-reconnects
      }
    };

    source.addEventListener("job-update", handle);
    return () => {
      source.removeEventListener("job-update", handle);
      source.close();
    };
  }, [token, applyEvent, pushToast]);
}

function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

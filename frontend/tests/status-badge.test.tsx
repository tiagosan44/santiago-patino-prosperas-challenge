import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "../src/components/StatusBadge";

describe("StatusBadge", () => {
  it("renders the label for each status", () => {
    for (const [status, label] of [
      ["PENDING", "Pending"],
      ["PROCESSING", "Processing"],
      ["COMPLETED", "Completed"],
      ["FAILED", "Failed"],
    ] as const) {
      const { unmount } = render(<StatusBadge status={status} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });
});

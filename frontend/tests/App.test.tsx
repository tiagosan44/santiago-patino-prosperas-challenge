import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../src/App";

describe("App", () => {
  it("renders the heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /prosperas reports/i })).toBeInTheDocument();
  });

  it("shows bootstrap message", () => {
    render(<App />);
    expect(screen.getByText(/bootstrap complete/i)).toBeInTheDocument();
  });
});

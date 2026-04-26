import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../src/App";
import { useAuthStore } from "../src/store/auth";

describe("App", () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, username: null, loginError: null, isLoggingIn: false });
  });

  it("renders LoginPage when not authenticated", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /prosperas reports/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("renders DashboardPage when authenticated", () => {
    useAuthStore.setState({ token: "tok", username: "alice" });
    render(<App />);
    expect(screen.getByText(/sign out/i)).toBeInTheDocument();
    expect(screen.getByText(/@alice/i)).toBeInTheDocument();
  });
});

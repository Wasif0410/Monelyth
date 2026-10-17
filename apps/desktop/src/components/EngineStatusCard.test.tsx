import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EngineStatusCard } from "@/components/EngineStatusCard";
import type { EngineStatus } from "@/engine/status";
import type { HealthState } from "@/engine/useEngineHealth";

const READY: EngineStatus = {
  state: "ready",
  port: 51234,
  token: "s3cr3t-token-value",
  version: "0.1.0",
};

function renderCard(status: EngineStatus, health: HealthState) {
  render(<EngineStatusCard status={status} health={health} />);
  return screen.getByRole("status");
}

describe("EngineStatusCard", () => {
  it("shows that the engine is starting", () => {
    const status = renderCard({ state: "starting" }, { kind: "idle" });

    expect(status).toHaveTextContent("Starting the engine…");
    expect(status).toHaveAttribute("aria-busy", "true");
  });

  it("shows that it is connecting while the health check runs", () => {
    const status = renderCard(READY, { kind: "checking" });

    expect(status).toHaveTextContent("Connecting to the engine…");
    expect(status).toHaveAttribute("aria-busy", "true");
  });

  it("shows a connected engine with its version", () => {
    const status = renderCard(READY, { kind: "ok", version: "0.1.0" });

    expect(status).toHaveTextContent("Engine connected");
    expect(status).toHaveTextContent("Version 0.1.0");
    expect(status).toHaveAttribute("aria-busy", "false");
  });

  it("shows a failed health check", () => {
    const status = renderCard(READY, {
      kind: "error",
      message: "The engine could not be reached.",
    });

    expect(status).toHaveTextContent("The engine isn't responding");
    expect(status).toHaveTextContent("The engine could not be reached.");
  });

  it("shows a failed start with recovery advice", () => {
    const status = renderCard({ state: "failed", message: "Port in use." }, { kind: "idle" });

    expect(status).toHaveTextContent("The engine couldn't start");
    expect(status).toHaveTextContent("Port in use. Restart Monelyth to try again.");
  });

  it("never shows the token", () => {
    const status = renderCard(READY, { kind: "ok", version: "0.1.0" });

    expect(status).not.toHaveTextContent("s3cr3t-token-value");
  });
});

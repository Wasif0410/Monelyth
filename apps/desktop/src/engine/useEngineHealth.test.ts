import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EngineStatus } from "@/engine/status";
import { useEngineHealth, type HealthState } from "@/engine/useEngineHealth";

const READY: EngineStatus = { state: "ready", port: 51234, token: "tok", version: "0.1.0" };

describe("useEngineHealth", () => {
  it("is idle until the engine is ready", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useEngineHealth({ state: "starting" }));

    expect(result.current).toEqual({ kind: "idle" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("checks health once the engine is ready", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(Response.json({ status: "ok", version: "0.1.0" }))),
    );

    const { result } = renderHook(() => useEngineHealth(READY));

    expect(result.current).toEqual({ kind: "checking" });
    await waitFor(() => {
      expect(result.current).toEqual({ kind: "ok", version: "0.1.0" });
    });
  });

  it("reports a failed health check", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response(null, { status: 500 }))),
    );

    const { result } = renderHook(() => useEngineHealth(READY));

    await waitFor(() => {
      expect(result.current).toEqual({
        kind: "error",
        message: "The engine responded with HTTP 500.",
      });
    });
  });

  it("goes back to checking when the connection changes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(Response.json({ status: "ok", version: "0.1.0" }))),
    );
    const { result, rerender } = renderHook<HealthState, EngineStatus>(
      (status) => useEngineHealth(status),
      {
        initialProps: READY,
      },
    );
    await waitFor(() => {
      expect(result.current.kind).toBe("ok");
    });

    rerender({ ...READY, port: 60000 });

    expect(result.current).toEqual({ kind: "checking" });
  });

  it("returns to idle when the engine stops being ready", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(Response.json({ status: "ok", version: "0.1.0" }))),
    );
    const { result, rerender } = renderHook<HealthState, EngineStatus>(
      (status) => useEngineHealth(status),
      {
        initialProps: READY,
      },
    );
    await waitFor(() => {
      expect(result.current.kind).toBe("ok");
    });

    rerender({ state: "failed", message: "Engine crashed." });

    expect(result.current).toEqual({ kind: "idle" });
  });
});

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ENGINE_STATUS_EVENT, GET_ENGINE_STATUS_COMMAND } from "@/engine/status";
import { useEngineStatus } from "@/engine/useEngineStatus";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));

const invokeMock = vi.mocked(invoke);
const listenMock = vi.mocked(listen);

const READY = { seq: 1, state: "ready", port: 51234, token: "tok", version: "0.1.0" };

let emit: (payload: unknown) => void;
let unlisten: ReturnType<typeof vi.fn<() => void>>;

beforeEach(() => {
  unlisten = vi.fn<() => void>();
  listenMock.mockImplementation((_event, handler) => {
    emit = (payload) => {
      handler({ event: ENGINE_STATUS_EVENT, id: 0, payload });
    };
    return Promise.resolve(unlisten);
  });
});

describe("useEngineStatus", () => {
  it("starts in the starting state", () => {
    invokeMock.mockReturnValue(new Promise(() => undefined));

    const { result } = renderHook(() => useEngineStatus());

    expect(result.current).toEqual({ state: "starting" });
  });

  it("subscribes before asking for the current status", async () => {
    invokeMock.mockResolvedValue(READY);

    const { result } = renderHook(() => useEngineStatus());

    await waitFor(() => {
      expect(result.current.state).toBe("ready");
    });
    expect(listenMock).toHaveBeenCalledWith(ENGINE_STATUS_EVENT, expect.any(Function));
    expect(invokeMock).toHaveBeenCalledWith(GET_ENGINE_STATUS_COMMAND);
    expect(listenMock.mock.invocationCallOrder[0]).toBeLessThan(
      invokeMock.mock.invocationCallOrder[0] ?? 0,
    );
    expect(result.current).toEqual({
      state: "ready",
      port: 51234,
      token: "tok",
      version: "0.1.0",
    });
  });

  it("applies newer events", async () => {
    invokeMock.mockResolvedValue(READY);
    const { result } = renderHook(() => useEngineStatus());
    await waitFor(() => {
      expect(result.current.state).toBe("ready");
    });

    act(() => {
      emit({ seq: 2, state: "failed", message: "Engine crashed." });
    });

    expect(result.current).toEqual({ state: "failed", message: "Engine crashed." });
  });

  it("ignores a snapshot older than the one it already has", async () => {
    let resolveInvoke: (value: unknown) => void = () => undefined;
    invokeMock.mockReturnValue(
      new Promise((resolve) => {
        resolveInvoke = resolve;
      }),
    );
    const { result } = renderHook(() => useEngineStatus());
    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalled();
    });

    act(() => {
      emit({ seq: 3, state: "failed", message: "Engine crashed." });
    });
    await act(async () => {
      resolveInvoke(READY);
      await Promise.resolve();
    });

    expect(result.current).toEqual({ state: "failed", message: "Engine crashed." });
  });

  it("reports a malformed status as a failure", async () => {
    invokeMock.mockResolvedValue({ seq: 0, state: "nonsense" });

    const { result } = renderHook(() => useEngineStatus());

    await waitFor(() => {
      expect(result.current.state).toBe("failed");
    });
  });

  it("reports a broken connection to the shell", async () => {
    listenMock.mockRejectedValue(new Error("IPC unavailable"));

    const { result } = renderHook(() => useEngineStatus());

    await waitFor(() => {
      expect(result.current).toEqual({
        state: "failed",
        message: "Could not reach the app shell: IPC unavailable",
      });
    });
  });

  it("unsubscribes on unmount", async () => {
    invokeMock.mockResolvedValue(READY);
    const { result, unmount } = renderHook(() => useEngineStatus());
    await waitFor(() => {
      expect(result.current.state).toBe("ready");
    });

    unmount();

    expect(unlisten).toHaveBeenCalledOnce();
  });
});

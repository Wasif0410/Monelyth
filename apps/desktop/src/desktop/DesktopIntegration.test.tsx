import { isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import { load } from "@tauri-apps/plugin-store";
import { act, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopIntegration } from "@/desktop/DesktopIntegration";
import { renderWithApi } from "@/test/renderWithApi";

vi.mock("@tauri-apps/api/core", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tauri-apps/api/core")>()),
  isTauri: vi.fn(),
}));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-autostart", () => ({ isEnabled: vi.fn(() => Promise.resolve(false)) }));
vi.mock("@tauri-apps/plugin-store", () => ({ load: vi.fn() }));

let emitNavigate: (payload: unknown) => void = () => undefined;
const unlisten = vi.fn();

function status(runsFinished: number, processed: number) {
  return {
    state: "idle",
    processed,
    total: processed,
    last_error: null,
    runs_finished: runsFinished,
  };
}

beforeEach(() => {
  vi.mocked(isTauri).mockReturnValue(true);
  vi.mocked(listen).mockImplementation((_event, handler) => {
    emitNavigate = (payload) => {
      handler({ event: "navigate", id: 1, payload });
    };
    return Promise.resolve(unlisten);
  });
  vi.mocked(isPermissionGranted).mockResolvedValue(true);
  vi.mocked(requestPermission).mockResolvedValue("granted");
  vi.mocked(load).mockResolvedValue({
    get: () => Promise.resolve(undefined),
  } as unknown as Awaited<ReturnType<typeof load>>);
  // The user is in another app.
  vi.spyOn(document, "hasFocus").mockReturnValue(false);
});

describe("tray navigation", () => {
  it("opens a known screen", async () => {
    const navigate = vi.fn();
    renderWithApi(<DesktopIntegration navigate={navigate} />, {
      routes: { "GET /categorization/status": status(0, 0) },
    });
    await waitFor(() => {
      expect(listen).toHaveBeenCalled();
    });

    act(() => {
      emitNavigate("/import");
    });

    expect(navigate).toHaveBeenCalledWith("/import");
  });

  it("ignores anything that isn't a known screen", async () => {
    const navigate = vi.fn();
    renderWithApi(<DesktopIntegration navigate={navigate} />, {
      routes: { "GET /categorization/status": status(0, 0) },
    });
    await waitFor(() => {
      expect(listen).toHaveBeenCalled();
    });

    act(() => {
      emitNavigate("https://evil.example");
      emitNavigate({ path: "/import" });
    });

    expect(navigate).not.toHaveBeenCalled();
  });

  it("stops listening when unmounted", async () => {
    const { unmount } = renderWithApi(<DesktopIntegration navigate={vi.fn()} />, {
      routes: { "GET /categorization/status": status(0, 0) },
    });
    await waitFor(() => {
      expect(listen).toHaveBeenCalled();
    });

    unmount();

    expect(unlisten).toHaveBeenCalled();
  });
});

describe("finished-run notification", () => {
  it("notifies when a run finishes while the user is elsewhere", async () => {
    let current = status(0, 0);
    const { queryClient } = renderWithApi(<DesktopIntegration navigate={vi.fn()} />, {
      routes: { "GET /categorization/status": () => Response.json(current) },
    });
    await waitFor(() => {
      expect(queryClient.isFetching()).toBe(0);
    });

    current = status(1, 84);
    await act(() => queryClient.invalidateQueries());

    await waitFor(() => {
      expect(sendNotification).toHaveBeenCalledWith({
        title: "Categorizing finished",
        body: "84 transactions were categorized. Open Monelyth to review them.",
      });
    });
  });

  it("stays quiet when the user is looking at Monelyth", async () => {
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    let current = status(0, 0);
    const { queryClient } = renderWithApi(<DesktopIntegration navigate={vi.fn()} />, {
      routes: { "GET /categorization/status": () => Response.json(current) },
    });
    await waitFor(() => {
      expect(queryClient.isFetching()).toBe(0);
    });

    current = status(1, 84);
    await act(() => queryClient.invalidateQueries());

    expect(sendNotification).not.toHaveBeenCalled();
  });

  it("doesn't notify about the run that finished before the app opened", async () => {
    renderWithApi(<DesktopIntegration navigate={vi.fn()} />, {
      routes: { "GET /categorization/status": status(5, 84) },
    });
    await waitFor(() => {
      expect(listen).toHaveBeenCalled();
    });

    expect(sendNotification).not.toHaveBeenCalled();
  });
});

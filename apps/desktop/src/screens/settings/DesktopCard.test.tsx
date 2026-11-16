import { isTauri } from "@tauri-apps/api/core";
import { disable, enable, isEnabled } from "@tauri-apps/plugin-autostart";
import { load } from "@tauri-apps/plugin-store";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopCard } from "@/screens/settings/DesktopCard";
import { renderWithApi } from "@/test/renderWithApi";

vi.mock("@tauri-apps/api/core", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tauri-apps/api/core")>()),
  isTauri: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-autostart", () => ({
  enable: vi.fn(),
  disable: vi.fn(),
  isEnabled: vi.fn(),
}));
vi.mock("@tauri-apps/plugin-store", () => ({ load: vi.fn() }));

const stored = new Map<string, unknown>();
const store = {
  get: vi.fn((key: string) => Promise.resolve(stored.get(key))),
  set: vi.fn((key: string, value: unknown) => {
    stored.set(key, value);
    return Promise.resolve();
  }),
  save: vi.fn(() => Promise.resolve()),
};

beforeEach(() => {
  stored.clear();
  vi.mocked(isTauri).mockReturnValue(true);
  vi.mocked(isEnabled).mockResolvedValue(false);
  vi.mocked(enable).mockResolvedValue();
  vi.mocked(disable).mockResolvedValue();
  vi.mocked(load).mockResolvedValue(store as unknown as Awaited<ReturnType<typeof load>>);
});

/** A preference switch, once the saved preferences have loaded and it can be used. */
async function switchFor(name: RegExp) {
  const toggle = await screen.findByRole("switch", { name });
  await waitFor(() => {
    expect(toggle).toBeEnabled();
  });
  return toggle;
}

describe("DesktopCard", () => {
  it("shows the saved preferences", async () => {
    stored.set("closeToTray", true);
    stored.set("notifications", false);
    vi.mocked(isEnabled).mockResolvedValue(true);

    renderWithApi(<DesktopCard />);

    expect(await switchFor(/sign in/)).toBeChecked();
    expect(await switchFor(/tray/)).toBeChecked();
    expect(await switchFor(/^Notifications/)).not.toBeChecked();
  });

  it("defaults to quitting on close, with notifications on", async () => {
    renderWithApi(<DesktopCard />);

    expect(await switchFor(/tray/)).not.toBeChecked();
    expect(await switchFor(/^Notifications/)).toBeChecked();
    expect(await switchFor(/sign in/)).not.toBeChecked();
  });

  it("turns start at sign-in on through Windows, not the store", async () => {
    renderWithApi(<DesktopCard />);

    fireEvent.click(await switchFor(/sign in/));

    await waitFor(() => {
      expect(enable).toHaveBeenCalledOnce();
    });
    expect(store.set).not.toHaveBeenCalled();
  });

  it("saves close-to-tray immediately so the shell sees it", async () => {
    renderWithApi(<DesktopCard />);

    fireEvent.click(await switchFor(/tray/));

    await waitFor(() => {
      expect(store.save).toHaveBeenCalled();
    });
    expect(stored.get("closeToTray")).toBe(true);
  });

  it("puts the switch back and explains when a change fails", async () => {
    vi.mocked(enable).mockRejectedValue(new Error("Access denied"));
    renderWithApi(<DesktopCard />);
    const toggle = await switchFor(/sign in/);

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(toggle).not.toBeChecked();
    });
  });
});

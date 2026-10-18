import { getVersion } from "@tauri-apps/api/app";
import { open } from "@tauri-apps/plugin-dialog";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { paths } from "@/paths";
import { formatBytes } from "@/screens/settings/format";
import { settingsKeys, type SystemInfo } from "@/screens/settings/queries";
import { SettingsScreen } from "@/screens/settings/SettingsScreen";
import { renderWithApi } from "@/test/renderWithApi";

vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ getVersion: vi.fn() }));

const openDialog = vi.mocked(open);
const writeText = vi.fn<(text: string) => Promise<void>>();

const INFO: SystemInfo = {
  engine_version: "0.1.0",
  data_folder: "C:\\Users\\me\\AppData\\Roaming\\Monelyth",
  database_path: "C:\\Users\\me\\AppData\\Roaming\\Monelyth\\monelyth.db",
  database_size_bytes: 1_572_864,
  account_count: 2,
  transaction_count: 1_234,
};

const EXPORT_PATH = "D:\\Backups\\Monelyth export 2026-10-17 090507";

function renderScreen(routes: Record<string, unknown> = {}) {
  return renderWithApi(<SettingsScreen />, {
    path: paths.settings,
    routes: { "GET /system/info": INFO, ...routes },
    extraRoutes: [
      { path: paths.welcome, element: <p>Welcome screen</p> },
      { path: paths.accounts, element: <p>Accounts screen</p> },
      { path: paths.transactions, element: <p>Transactions screen</p> },
    ],
  });
}

function section(name: string) {
  return screen.getByRole("region", { name });
}

beforeEach(() => {
  vi.mocked(getVersion).mockResolvedValue("0.1.2");
  openDialog.mockReset();
  writeText.mockReset().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
});

describe("SettingsScreen data location", () => {
  it("shows where the data lives, its size and what it holds", async () => {
    renderScreen();

    const data = await screen.findByRole("region", { name: "Your data" });
    expect(await within(data).findByText(INFO.data_folder)).toBeInTheDocument();
    expect(within(data).getByText(formatBytes(INFO.database_size_bytes))).toBeInTheDocument();
    expect(within(data).getByRole("link", { name: "2 accounts" })).toHaveTextContent("2");
    const transactions = within(data).getByRole("link", {
      name: `${(1_234).toLocaleString()} transactions`,
    });

    fireEvent.click(transactions);
    expect(await screen.findByText("Transactions screen")).toBeInTheDocument();
  });

  it("shows the app and engine versions", async () => {
    renderScreen();

    expect(await screen.findByText("Monelyth 0.1.2 · engine 0.1.0")).toBeInTheDocument();
  });

  it("copies the data folder path", async () => {
    renderScreen();

    fireEvent.click(await screen.findByRole("button", { name: "Copy data folder path" }));

    expect(await screen.findByText("Copied")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(INFO.data_folder);
  });

  it("shows a placeholder while loading", () => {
    renderScreen({ "GET /system/info": () => new Promise<Response>(() => undefined) });

    expect(screen.getByRole("status", { name: "Loading data location" })).toBeInTheDocument();
  });

  it("shows a retryable error", async () => {
    renderScreen({
      "GET /system/info": () => Response.json({ detail: "Database locked." }, { status: 503 }),
    });

    const data = section("Your data");
    expect(await within(data).findByRole("alert")).toHaveTextContent("Database locked.");
    expect(within(data).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("SettingsScreen export", () => {
  it("exports to the folder picked in the native dialog", async () => {
    openDialog.mockResolvedValue("D:\\Backups");
    const bodies: unknown[] = [];
    renderScreen({
      "POST /data/export": async (request: Request) => {
        bodies.push(await request.json());
        return Response.json({ path: EXPORT_PATH, transaction_count: 1_234 }, { status: 201 });
      },
    });

    const exporting = section("Export everything");
    fireEvent.click(within(exporting).getByRole("button", { name: "Export everything…" }));

    const result = await within(exporting).findByRole("status");
    expect(result).toHaveTextContent(`Exported ${(1_234).toLocaleString()} transactions to:`);
    expect(result).toHaveTextContent(EXPORT_PATH);
    expect(openDialog).toHaveBeenCalledWith(expect.objectContaining({ directory: true }));
    expect(bodies).toEqual([{ folder: "D:\\Backups" }]);

    fireEvent.click(within(result).getByRole("button", { name: "Copy export folder path" }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(EXPORT_PATH);
    });
  });

  it("does nothing when the user cancels the folder picker", async () => {
    openDialog.mockResolvedValue(null);
    const { fetchMock } = renderScreen();

    const exporting = section("Export everything");
    const button = within(exporting).getByRole("button", { name: "Export everything…" });
    fireEvent.click(button);

    await waitFor(() => {
      expect(button).toBeEnabled();
    });
    expect(openDialog).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls.map(([request]) => request.method)).not.toContain("POST");
    expect(within(exporting).queryByRole("status")).not.toBeInTheDocument();
    expect(within(exporting).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains a failed export", async () => {
    openDialog.mockResolvedValue("D:\\Locked");
    renderScreen({
      "POST /data/export": () =>
        Response.json(
          {
            detail: "Monelyth can't create files in D:\\Locked. Choose a folder you can write to.",
          },
          { status: 422 },
        ),
    });

    const exporting = section("Export everything");
    fireEvent.click(within(exporting).getByRole("button", { name: "Export everything…" }));

    expect(await within(exporting).findByRole("alert")).toHaveTextContent(
      "Monelyth can't create files in D:\\Locked.",
    );
  });
});

describe("SettingsScreen delete everything", () => {
  it("enables the button only once DELETE is typed exactly", () => {
    renderScreen();

    const danger = section("Delete everything");
    const input = within(danger).getByLabelText("Type DELETE to confirm");
    const button = within(danger).getByRole("button", { name: "Delete everything" });
    expect(button).toBeDisabled();

    for (const value of ["delete", "DELET", "DELETE ", " DELETE"]) {
      fireEvent.change(input, { target: { value } });
      expect(button).toBeDisabled();
    }
    fireEvent.change(input, { target: { value: "DELETE" } });
    expect(button).toBeEnabled();
  });

  it("erases everything, clears the cache and goes to the welcome screen", async () => {
    const bodies: unknown[] = [];
    const { queryClient } = renderScreen({
      "POST /data/erase": async (request: Request) => {
        bodies.push(await request.json());
        return Response.json({ deleted_accounts: 2, deleted_transactions: 1_234 });
      },
    });
    await screen.findByText(INFO.data_folder);
    queryClient.setQueryData(["transactions", { page: 1 }], { items: [], total: 9 });

    const danger = section("Delete everything");
    fireEvent.change(within(danger).getByLabelText("Type DELETE to confirm"), {
      target: { value: "DELETE" },
    });
    fireEvent.click(within(danger).getByRole("button", { name: "Delete everything" }));

    expect(await screen.findByText("Welcome screen")).toBeInTheDocument();
    expect(bodies).toEqual([{ confirm: "DELETE" }]);
    expect(queryClient.getQueryData(["transactions", { page: 1 }])).toBeUndefined();
    expect(queryClient.getQueryData(settingsKeys.systemInfo)).toBeUndefined();
  });

  it("stays put and explains a failed erase", async () => {
    renderScreen({
      "POST /data/erase": () => Response.json({ detail: "Database locked." }, { status: 503 }),
    });

    const danger = section("Delete everything");
    fireEvent.change(within(danger).getByLabelText("Type DELETE to confirm"), {
      target: { value: "DELETE" },
    });
    fireEvent.click(within(danger).getByRole("button", { name: "Delete everything" }));

    expect(await within(danger).findByRole("alert")).toHaveTextContent("Database locked.");
    expect(screen.queryByText("Welcome screen")).not.toBeInTheDocument();
  });
});

describe("formatBytes", () => {
  it.each([
    [4_096, "4 kB"],
    [1_572_864, "1.5 MB"],
    [52_428_800, "50 MB"],
    [3 * 1024 ** 3, "3 GB"],
  ])("formats %i bytes", (bytes, expected) => {
    expect(formatBytes(bytes, "en-US")).toBe(expected);
  });
});

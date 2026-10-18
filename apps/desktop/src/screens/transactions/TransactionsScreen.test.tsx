import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Toaster } from "sonner";
import { beforeEach, describe, expect, it, type Mock } from "vitest";

import { formatMoney } from "@/lib/format";
import { paths } from "@/paths";
import { PAGE_SIZE, type Transaction } from "@/screens/transactions/hooks";
import {
  accounts,
  bookstore,
  categories,
  groceries,
  payroll,
  range,
  stubLayout,
  transaction,
} from "@/screens/transactions/testData";
import { ROW_HEIGHT } from "@/screens/transactions/TransactionsTable";
import { TransactionsScreen } from "@/screens/transactions/TransactionsScreen";
import { renderWithApi, type StubRoutes } from "@/test/renderWithApi";

beforeEach(() => {
  stubLayout();
});

type Rows = readonly Transaction[] | ((request: Request) => Response | Promise<Response>);

function renderScreen({
  rows = [groceries, payroll, bookstore],
  ...routes
}: StubRoutes & { rows?: Rows } = {}) {
  const listRoute =
    typeof rows === "function"
      ? rows
      : (request: Request) => Response.json(pageOf(rows, new URL(request.url).searchParams));
  return renderWithApi(
    <>
      <TransactionsScreen />
      <Toaster />
    </>,
    {
      routes: {
        "GET /accounts": accounts,
        "GET /categories": categories,
        "GET /transactions/range": range,
        "GET /transactions": listRoute,
        ...routes,
      },
      extraRoutes: [{ path: paths.import, element: <p>Import screen</p> }],
    },
  );
}

/** The page a real engine would return for these query parameters. */
function pageOf(rows: readonly Transaction[], params: URLSearchParams) {
  const offset = Number(params.get("offset") ?? "0");
  const limit = Number(params.get("limit") ?? "100");
  return { items: rows.slice(offset, offset + limit), total: rows.length };
}

/** The query parameters of every request to `GET /transactions`, oldest first. */
function listRequests(fetchMock: Mock<(request: Request) => Promise<Response>>) {
  return fetchMock.mock.calls
    .map(([request]) => new URL(request.url))
    .filter((url) => url.pathname === "/transactions")
    .map((url) => Object.fromEntries(url.searchParams));
}

function patchRequests(fetchMock: Mock<(request: Request) => Promise<Response>>) {
  return fetchMock.mock.calls
    .map(([request]) => request)
    .filter((request) => request.method === "PATCH");
}

function row(name: string) {
  const cell = screen.getByText(name, { selector: "p" });
  const tableRow = cell.closest("tr");
  if (!tableRow) throw new Error(`No row for ${name}`);
  return within(tableRow);
}

/** Open a Radix select with the keyboard and choose an option, as a keyboard user would. */
async function choose(trigger: HTMLElement, option: string) {
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "Enter" });
  const item = await screen.findByRole("option", { name: option });
  fireEvent.keyDown(item, { key: "Enter" });
}

describe("TransactionsScreen", () => {
  it("lists transactions with their details and formatted money", async () => {
    renderScreen();

    expect(await screen.findByText("3 transactions")).toBeInTheDocument();
    const loblaws = row("Loblaws");
    expect(loblaws.getByText("POS PURCHASE LOBLAWS #1031 TORONTO ON")).toBeInTheDocument();
    expect(loblaws.getByText("Everyday Chequing")).toBeInTheDocument();
    expect(loblaws.getByText(formatMoney(-8210, "CAD"))).toBeInTheDocument();
    expect(loblaws.getByRole("combobox", { name: "Category for Loblaws" })).toHaveTextContent(
      "Uncategorized",
    );

    const income = row("Acme Corp").getByText(`+${formatMoney(250000, "CAD")}`);
    expect(income).toHaveClass("text-success");
    expect(row("Acme Corp").getByRole("combobox")).toHaveTextContent("Salary");

    // No cleaned merchant name: the bank's description stands in. The card is in US dollars.
    const amazon = row("AMZN MKTP US*2K3 BOOKS");
    expect(amazon.getByText(formatMoney(-1299, "USD"))).not.toHaveClass("text-success");
    expect(amazon.getByRole("img", { name: "Needs review" })).toBeInTheDocument();

    expect(screen.getByRole("table", { name: "Transactions" })).toHaveAttribute(
      "aria-rowcount",
      "4",
    );
  });

  it("shows a loading skeleton first", async () => {
    renderScreen();

    expect(screen.getByRole("status", { name: "Loading transactions" })).toBeInTheDocument();
    expect(await screen.findByText("Loblaws")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading transactions" })).not.toBeInTheDocument();
  });

  it("points to the import screen before anything is imported", async () => {
    renderScreen({ rows: [], "GET /transactions/range": { first_date: null, last_date: null } });

    expect(await screen.findByRole("heading", { name: "No transactions yet" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Import a statement" }));
    expect(await screen.findByText("Import screen")).toBeInTheDocument();
  });

  it("explains when nothing matches the filters, and clears them", async () => {
    const { fetchMock, router } = renderScreen({
      rows: (request) => {
        const filtered = new URL(request.url).searchParams.has("needs_review");
        return Response.json({ items: filtered ? [] : [groceries], total: filtered ? 0 : 1 });
      },
    });
    await screen.findByText("Loblaws");

    fireEvent.click(screen.getByRole("button", { name: "Needs review" }));

    expect(
      await screen.findByRole("heading", { name: "No matching transactions" }),
    ).toBeInTheDocument();
    expect(screen.getByText("0 transactions")).toBeInTheDocument();

    // One in the toolbar, one in the message.
    const [, inMessage] = screen.getAllByRole("button", { name: "Clear filters" });
    if (!inMessage) throw new Error("No Clear filters button in the message");
    fireEvent.click(inMessage);

    expect(await screen.findByText("Loblaws")).toBeInTheDocument();
    expect(router.state.location.search).toBe("");
    expect(screen.getByRole("button", { name: "Needs review" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(listRequests(fetchMock).at(-1)).toEqual({ limit: String(PAGE_SIZE), offset: "0" });
  });

  it("puts each filter in the URL and in the request", async () => {
    const { fetchMock, router } = renderScreen();
    await screen.findByText("Loblaws");

    fireEvent.click(screen.getByRole("button", { name: "Needs review" }));
    await waitFor(() => {
      expect(router.state.location.search).toBe("?review=1");
    });

    await choose(screen.getByRole("combobox", { name: "Account" }), "Travel Visa");
    await waitFor(() => {
      expect(router.state.location.search).toBe("?account=2&review=1");
    });

    await choose(screen.getByRole("combobox", { name: "Category" }), "Uncategorized");
    // From "All time", the previous-month arrow goes to the latest month with transactions.
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    await waitFor(() => {
      expect(router.state.location.search).toBe(
        "?account=2&month=2026-10&category=uncategorized&review=1",
      );
    });
    expect(screen.getByRole("combobox", { name: "Month" })).toHaveTextContent("October 2026");
    expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();

    fireEvent.change(screen.getByRole("searchbox", { name: "Search transactions" }), {
      target: { value: "loblaws " },
    });
    await waitFor(() => {
      expect(router.state.location.search).toBe(
        "?q=loblaws&account=2&month=2026-10&category=uncategorized&review=1",
      );
    });
    // The URL drops the trailing space, but the field keeps what was typed.
    expect(screen.getByRole("searchbox", { name: "Search transactions" })).toHaveValue("loblaws ");

    await waitFor(() => {
      expect(listRequests(fetchMock).at(-1)).toEqual({
        q: "loblaws",
        account_id: "2",
        date_from: "2026-10-01",
        date_to: "2026-10-31",
        categorized: "false",
        needs_review: "true",
        limit: String(PAGE_SIZE),
        offset: "0",
      });
    });
  });

  it("opens an exact filtered view from a link", async () => {
    const { fetchMock, router } = renderScreen();
    await act(() => router.navigate("/?month=2026-09&category=5"));

    await waitFor(() => {
      expect(listRequests(fetchMock).at(-1)).toEqual({
        date_from: "2026-09-01",
        date_to: "2026-09-30",
        category_id: "5",
        limit: String(PAGE_SIZE),
        offset: "0",
      });
    });
    expect(await screen.findByRole("combobox", { name: "Month" })).toHaveTextContent(
      "September 2026",
    );
    expect(screen.getByRole("combobox", { name: "Category" })).toHaveTextContent("Groceries");
  });

  it("saves a new category at once and keeps it after the engine confirms", async () => {
    let confirm: (response: Response) => void = () => undefined;
    const { fetchMock } = renderScreen({
      "PATCH /transactions/3": () =>
        new Promise<Response>((resolve) => {
          confirm = resolve;
        }),
    });
    await screen.findByText("Loblaws");

    await choose(screen.getByRole("combobox", { name: "Category for Loblaws" }), "Groceries");

    // Shown before the engine has answered.
    const trigger = screen.getByRole("combobox", { name: "Category for Loblaws" });
    await waitFor(() => {
      expect(trigger).toHaveTextContent("Groceries");
    });
    const [patch] = patchRequests(fetchMock);
    expect(patch?.url).toMatch(/\/transactions\/3$/);
    expect(await patch?.json()).toEqual({ category_id: 5 });

    const listsBefore = listRequests(fetchMock).length;
    confirm(
      Response.json({ ...groceries, category_id: 5, category_source: "user", needs_review: false }),
    );
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([r]) => r.url.endsWith("/range"))).toHaveLength(2);
    });
    expect(trigger).toHaveTextContent("Groceries");
    // This view doesn't filter by category, so its rows stay as they are: no reload.
    expect(listRequests(fetchMock)).toHaveLength(listsBefore);
  });

  it("reloads a category-filtered view after a change, since the row may leave it", async () => {
    const { fetchMock, router } = renderScreen({
      "PATCH /transactions/3": { ...groceries, category_id: 5, category_source: "user" },
    });
    await act(() => router.navigate("/?category=uncategorized"));
    await screen.findByText("Loblaws");
    const listsBefore = listRequests(fetchMock).length;

    await choose(screen.getByRole("combobox", { name: "Category for Loblaws" }), "Groceries");

    await waitFor(() => {
      expect(listRequests(fetchMock).length).toBeGreaterThan(listsBefore);
    });
    expect(listRequests(fetchMock).at(-1)).toMatchObject({ categorized: "false" });
  });

  it("puts the category back and says why when saving fails", async () => {
    renderScreen({
      "PATCH /transactions/3": () =>
        Response.json({ detail: "The database is locked." }, { status: 503 }),
    });
    await screen.findByText("Loblaws");

    await choose(screen.getByRole("combobox", { name: "Category for Loblaws" }), "Dining Out");

    expect(await screen.findByText("Couldn't change the category")).toBeInTheDocument();
    expect(screen.getByText("The database is locked.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Category for Loblaws" })).toHaveTextContent(
      "Uncategorized",
    );
  });

  it("loads the next page when scrolled near the end", async () => {
    const many = Array.from({ length: PAGE_SIZE * 2 + 50 }, (_, index) =>
      transaction({ id: 10_000 - index, merchant: `Shop ${String(index)}` }),
    );
    const { fetchMock } = renderScreen({ rows: many });
    expect(await screen.findByText(`${String(many.length)} transactions`)).toBeInTheDocument();
    // Only the rows in view are rendered.
    expect(screen.getByText("Shop 0")).toBeInTheDocument();
    expect(screen.queryByText("Shop 150")).not.toBeInTheDocument();
    expect(listRequests(fetchMock)).toHaveLength(1);

    scrollListTo(PAGE_SIZE * ROW_HEIGHT);

    expect(await screen.findByText(`Shop ${String(PAGE_SIZE + 5)}`)).toBeInTheDocument();
    expect(listRequests(fetchMock).map((params) => params.offset)).toEqual([
      "0",
      String(PAGE_SIZE),
    ]);
    expect(screen.queryByText("Shop 0")).not.toBeInTheDocument();
  });

  it("offers a retry when the next page fails to load", async () => {
    const many = Array.from({ length: PAGE_SIZE + 10 }, (_, index) =>
      transaction({ id: 10_000 - index, merchant: `Shop ${String(index)}` }),
    );
    let failNext = true;
    renderScreen({
      rows: (request) => {
        const params = new URL(request.url).searchParams;
        if (params.get("offset") !== "0" && failNext) {
          failNext = false;
          return Response.json({ detail: "The engine stopped." }, { status: 500 });
        }
        return Response.json(pageOf(many, params));
      },
    });
    await screen.findByText("Shop 0");

    scrollListTo(PAGE_SIZE * ROW_HEIGHT);

    expect(await screen.findByText(/Couldn't load more transactions/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(`Shop ${String(PAGE_SIZE + 5)}`)).toBeInTheDocument();
  });

  it("shows an error with a retry when transactions can't be loaded", async () => {
    renderScreen({
      rows: () => Response.json({ detail: "The engine stopped." }, { status: 500 }),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("The engine stopped.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

/** jsdom doesn't scroll: set the list's scroll position and tell the virtualizer. */
function scrollListTo(top: number) {
  const list = screen.getByRole("region", { name: "Transaction list" });
  Object.defineProperty(list, "scrollTop", { configurable: true, value: top });
  fireEvent.scroll(list);
}

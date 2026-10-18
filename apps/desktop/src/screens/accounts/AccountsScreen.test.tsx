import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useLocation } from "react-router";
import { describe, expect, it } from "vitest";

import type { Account } from "@/api/queries";
import { queryKeys } from "@/api/queries";
import { formatDate, formatMoney } from "@/lib/format";
import { paths } from "@/paths";
import { AccountsScreen } from "@/screens/accounts/AccountsScreen";
import { deletionSummary } from "@/screens/accounts/text";
import { renderWithApi } from "@/test/renderWithApi";

function makeAccount(overrides: Partial<Account> = {}): Account {
  return {
    id: 1,
    name: "Main Checking",
    institution: "TD",
    type: "checking",
    currency: "CAD",
    transaction_count: 158,
    latest_transaction_date: "2026-09-14",
    net_amount_cents: -123_456,
    ...overrides,
  };
}

/** An engine whose account list reflects the changes the screen makes. */
function accountsEngine(initial: Account[]) {
  let accounts = initial;
  const bodies: unknown[] = [];
  const routes = {
    "GET /accounts": () => Response.json(accounts),
    "POST /accounts": async (request: Request) => {
      const body = (await request.json()) as Pick<Account, "name" | "type" | "currency">;
      bodies.push(body);
      const created = makeAccount({
        ...body,
        id: 99,
        institution: null,
        transaction_count: 0,
        latest_transaction_date: null,
        net_amount_cents: 0,
      });
      accounts = [...accounts, created];
      return Response.json(created, { status: 201 });
    },
    "PATCH /accounts/1": async (request: Request) => {
      const body = (await request.json()) as Partial<Account>;
      bodies.push(body);
      const updated = { ...accounts[0], ...body } as Account;
      accounts = accounts.map((account) => (account.id === 1 ? updated : account));
      return Response.json(updated);
    },
    "DELETE /accounts/1": () => {
      accounts = accounts.filter((account) => account.id !== 1);
      return Response.json({ deleted_imports: 2, deleted_transactions: 158 });
    },
  };
  return { routes, bodies };
}

function LocationProbe() {
  const location = useLocation();
  return <p>At {location.pathname + location.search}</p>;
}

function renderScreen(routes: Record<string, unknown>) {
  return renderWithApi(<AccountsScreen />, {
    path: paths.accounts,
    routes,
    extraRoutes: [
      { path: paths.transactions, element: <LocationProbe /> },
      { path: paths.import, element: <LocationProbe /> },
    ],
  });
}

describe("AccountsScreen", () => {
  it("lists each account with its details and numbers", async () => {
    renderScreen({
      "GET /accounts": [
        makeAccount(),
        makeAccount({
          id: 2,
          name: "Visa",
          institution: null,
          type: "credit_card",
          transaction_count: 1,
          latest_transaction_date: "2026-10-02",
          net_amount_cents: 4_500,
        }),
      ],
    });

    const checking = await screen.findByRole("group", { name: "Main Checking" });
    expect(within(checking).getByText("TD · Checking · CAD")).toBeInTheDocument();
    expect(within(checking).getByText(formatDate("2026-09-14"))).toBeInTheDocument();
    expect(
      within(checking).getByRole("link", { name: "158 transactions in Main Checking" }),
    ).toHaveTextContent("158");
    expect(
      within(checking).getByRole("link", {
        name: `Net of imports for Main Checking: ${formatMoney(-123_456, "CAD")}`,
      }),
    ).toBeInTheDocument();

    const visa = screen.getByRole("group", { name: "Visa" });
    expect(within(visa).getByText("Credit card · CAD")).toBeInTheDocument();
    expect(within(visa).getByRole("link", { name: "1 transaction in Visa" })).toBeInTheDocument();
    expect(within(visa).getByText(formatMoney(4_500, "CAD"))).toBeInTheDocument();
  });

  it("links the transaction count to that account's transactions", async () => {
    renderScreen({ "GET /accounts": [makeAccount({ id: 7 })] });

    fireEvent.click(await screen.findByRole("link", { name: /158 transactions/ }));

    expect(await screen.findByText("At /transactions?account=7")).toBeInTheDocument();
  });

  it("offers an import for an account without transactions", async () => {
    renderScreen({
      "GET /accounts": [
        makeAccount({ transaction_count: 0, latest_transaction_date: null, net_amount_cents: 0 }),
      ],
    });

    expect(await screen.findByText(/No transactions yet/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /transactions in/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Import a statement" }));
    expect(await screen.findByText("At /import")).toBeInTheDocument();
  });

  it("shows placeholders while loading", () => {
    renderScreen({ "GET /accounts": () => new Promise<Response>(() => undefined) });

    expect(screen.getByRole("status", { name: "Loading accounts" })).toBeInTheDocument();
  });

  it("shows a retryable error", async () => {
    renderScreen({
      "GET /accounts": () => Response.json({ detail: "Database locked." }, { status: 503 }),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Database locked.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("invites a new user to add their first account", async () => {
    const engine = accountsEngine([]);
    renderScreen(engine.routes);

    expect(await screen.findByText("No accounts yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));

    expect(await screen.findByRole("dialog", { name: "Add account" })).toBeInTheDocument();
  });

  it("adds an account from the dialog", async () => {
    const engine = accountsEngine([makeAccount({ currency: "USD" })]);
    renderScreen(engine.routes);

    fireEvent.click(await screen.findByRole("button", { name: "Add account" }));
    const dialog = await screen.findByRole("dialog", { name: "Add account" });
    const submit = within(dialog).getByRole("button", { name: "Add account" });
    expect(submit).toBeDisabled();

    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "  Visa  " } });
    fireEvent.change(within(dialog).getByLabelText(/Institution/), {
      target: { value: " Chase " },
    });
    // The currency defaults to the one the user's accounts already use.
    expect(within(dialog).getByRole("combobox", { name: "Currency" })).toHaveTextContent("USD");
    fireEvent.click(within(dialog).getByRole("combobox", { name: "Type" }));
    fireEvent.click(await screen.findByRole("option", { name: "Credit card" }));
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(engine.bodies).toEqual([
      { name: "Visa", institution: "Chase", type: "credit_card", currency: "USD" },
    ]);
    expect(await screen.findByRole("group", { name: "Visa" })).toBeInTheDocument();
  });

  it("keeps the dialog open and explains a failed add", async () => {
    renderScreen({
      "GET /accounts": [makeAccount()],
      "POST /accounts": () => Response.json({ detail: "Disk is full." }, { status: 500 }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Add account" }));
    const dialog = await screen.findByRole("dialog", { name: "Add account" });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Visa" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add account" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Disk is full.");
  });

  it("renames an account in place", async () => {
    const engine = accountsEngine([makeAccount()]);
    const { queryClient } = renderScreen(engine.routes);
    const invalidated: unknown[] = [];
    const invalidate = queryClient.invalidateQueries.bind(queryClient);
    queryClient.invalidateQueries = (filters, options) => {
      invalidated.push(filters?.queryKey);
      return invalidate(filters, options);
    };

    fireEvent.click(await screen.findByRole("button", { name: "Rename Main Checking" }));
    const form = screen.getByRole("form", { name: "Rename Main Checking" });
    const name = within(form).getByLabelText("Name");
    expect(name).toHaveFocus();
    fireEvent.change(name, { target: { value: " Joint Checking " } });
    fireEvent.change(within(form).getByLabelText(/Institution/), { target: { value: "" } });
    fireEvent.submit(form);

    expect(await screen.findByRole("heading", { name: "Joint Checking" })).toBeInTheDocument();
    expect(engine.bodies).toEqual([{ name: "Joint Checking", institution: null }]);
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(invalidated).toEqual(
      expect.arrayContaining([queryKeys.accounts, queryKeys.transactions]),
    );
  });

  it("cancels a rename with Escape without saving", async () => {
    const engine = accountsEngine([makeAccount()]);
    renderScreen(engine.routes);

    fireEvent.click(await screen.findByRole("button", { name: "Rename Main Checking" }));
    const name = screen.getByLabelText("Name");
    fireEvent.change(name, { target: { value: "Something else" } });
    fireEvent.keyDown(name, { key: "Escape" });

    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Main Checking" })).toBeInTheDocument();
    expect(engine.bodies).toEqual([]);
  });

  it("deletes an account after confirming exactly what goes", async () => {
    const engine = accountsEngine([makeAccount(), makeAccount({ id: 2, name: "Savings" })]);
    const { fetchMock } = renderScreen(engine.routes);

    fireEvent.click(await screen.findByRole("button", { name: "Delete Main Checking" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete Main Checking?" });
    expect(dialog).toHaveTextContent(
      "Deletes Main Checking and its 158 transactions. This can't be undone.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete account" }));

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
    expect(screen.queryByRole("group", { name: "Main Checking" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Savings" })).toBeInTheDocument();
    const methods = fetchMock.mock.calls.map(([request]) => request.method);
    expect(methods.filter((method) => method === "DELETE")).toHaveLength(1);
  });

  it("keeps everything when the delete is cancelled", async () => {
    const engine = accountsEngine([makeAccount()]);
    const { fetchMock } = renderScreen(engine.routes);

    fireEvent.click(await screen.findByRole("button", { name: "Delete Main Checking" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("group", { name: "Main Checking" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([request]) => request.method === "GET")).toBe(true);
  });

  it("explains a failed delete and keeps the dialog open", async () => {
    renderScreen({
      "GET /accounts": [makeAccount()],
      "DELETE /accounts/1": () => Response.json({ detail: "Database locked." }, { status: 503 }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Delete Main Checking" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete account" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Database locked.");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });
});

describe("deletionSummary", () => {
  it.each([
    [0, "Deletes Cash, which has no transactions. This can't be undone."],
    [1, "Deletes Cash and its 1 transaction. This can't be undone."],
    [1580, `Deletes Cash and its ${(1580).toLocaleString()} transactions. This can't be undone.`],
  ])("describes an account with %i transactions", (count, expected) => {
    expect(deletionSummary(makeAccount({ name: "Cash", transaction_count: count }))).toBe(expected);
  });
});

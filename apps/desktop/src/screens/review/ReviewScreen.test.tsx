import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast, Toaster } from "sonner";
import { afterEach, describe, expect, it } from "vitest";

import { formatMoney } from "@/lib/format";
import { paths } from "@/paths";
import type { Transaction } from "@/screens/review/queries";
import { ReviewScreen } from "@/screens/review/ReviewScreen";
import { accounts, categories, transaction } from "@/screens/transactions/testData";
import { renderWithApi, type StubRoutes } from "@/test/renderWithApi";

afterEach(() => {
  // Sonner keeps toasts in a module-wide store; don't let one leak into the next test.
  toast.dismiss();
});

const bakery = transaction({
  id: 11,
  merchant: "Corner Bakery",
  description_raw: "SQ *CORNER BAKERY 0042",
  amount_cents: -850,
  category_id: 6,
  category_source: "classifier",
  confidence: 0.62,
  needs_review: true,
});
const books = transaction({
  id: 12,
  merchant: "Riverside Books",
  account_id: 2,
  amount_cents: -2100,
  category_id: 5,
  category_source: "llm",
  confidence: 0.55,
  needs_review: true,
});
const mystery = transaction({
  id: 13,
  merchant: "Mystery Shop",
  needs_review: true,
});

/** An engine whose review queue shrinks as the screen answers it. */
function reviewEngine(initial: readonly Transaction[], overrides: StubRoutes = {}) {
  let queue = [...initial];
  const bodies: { route: string; body: unknown }[] = [];
  const answer = async (route: string, request: Request) => {
    const body: unknown = await request.json();
    bodies.push({ route, body });
    return body;
  };
  const perTransaction: StubRoutes = {};
  for (const tx of initial) {
    perTransaction[`PATCH /transactions/${String(tx.id)}`] = async (request: Request) => {
      const body = (await answer("patch", request)) as { category_id: number };
      queue = queue.filter((item) => item.id !== tx.id);
      return Response.json({
        ...tx,
        category_id: body.category_id,
        category_source: "user",
        confidence: null,
        needs_review: false,
      });
    };
    perTransaction[`GET /transactions/${String(tx.id)}/same-merchant`] = {
      merchant: tx.merchant,
      count: 0,
    };
  }
  const routes: StubRoutes = {
    "GET /accounts": accounts,
    "GET /categories": categories,
    "GET /transactions": () => Response.json({ items: queue, total: queue.length }),
    "GET /review/summary": () =>
      Response.json({
        waiting: queue.length,
        with_suggestion: queue.filter((tx) => tx.category_id !== null).length,
      }),
    "POST /review/accept": async (request: Request) => {
      const { transaction_ids: ids } = (await answer("accept", request)) as {
        transaction_ids: number[];
      };
      queue = queue.filter((tx) => !ids.includes(tx.id));
      return Response.json({ accepted: ids.length });
    },
    "POST /review/accept-all": async (request: Request) => {
      await answer("accept-all", request);
      const accepted = queue.filter((tx) => tx.category_id !== null).length;
      queue = queue.filter((tx) => tx.category_id === null);
      return Response.json({ accepted });
    },
    ...perTransaction,
    ...overrides,
  };
  return { routes, bodies };
}

function renderScreen(engine: ReturnType<typeof reviewEngine>) {
  return renderWithApi(
    <>
      <ReviewScreen />
      <Toaster />
    </>,
    { path: paths.review, routes: engine.routes },
  );
}

function press(key: string) {
  fireEvent.keyDown(document.body, { key });
}

describe("ReviewScreen", () => {
  it("shows one transaction at a time with what Monelyth suggests", async () => {
    renderScreen(reviewEngine([bakery, books]));

    expect(await screen.findByRole("heading", { name: "Corner Bakery" })).toBeInTheDocument();
    expect(screen.getByText("SQ *CORNER BAKERY 0042")).toBeInTheDocument();
    expect(screen.getByText(formatMoney(-850, "CAD"))).toBeInTheDocument();
    expect(screen.getByText(/Everyday Chequing/)).toBeInTheDocument();
    expect(screen.getByText("Dining Out")).toBeInTheDocument();
    expect(screen.getByText("From the classifier, 62% sure")).toBeInTheDocument();
    expect(screen.getByText("2 transactions waiting")).toBeInTheDocument();
    expect(screen.queryByText("Riverside Books")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Accept all 2 suggestions/ })).toBeInTheDocument();
  });

  it("accepts the suggestion and moves on to the next transaction", async () => {
    const engine = reviewEngine([bakery, books]);
    renderScreen(engine);
    await screen.findByRole("heading", { name: "Corner Bakery" });

    fireEvent.click(screen.getByRole("button", { name: "Accept" }));

    expect(await screen.findByRole("heading", { name: "Riverside Books" })).toBeInTheDocument();
    expect(screen.getByText("From the local AI model, 55% sure")).toBeInTheDocument();
    expect(engine.bodies).toEqual([{ route: "accept", body: { transaction_ids: [11] } }]);
    await waitFor(() => {
      expect(screen.getByText("1 transaction waiting")).toBeInTheDocument();
    });
  });

  it("answers with the keyboard: A accepts, S skips, C chooses a category", async () => {
    const engine = reviewEngine([bakery, books, mystery]);
    renderScreen(engine);
    await screen.findByRole("heading", { name: "Corner Bakery" });

    press("s");
    expect(await screen.findByRole("heading", { name: "Riverside Books" })).toBeInTheDocument();
    expect(screen.getByText("3 transactions waiting, 1 skipped")).toBeInTheDocument();

    press("a");
    expect(await screen.findByRole("heading", { name: "Mystery Shop" })).toBeInTheDocument();

    press("c");
    const option = await screen.findByRole("option", { name: "Groceries" });
    fireEvent.keyDown(option, { key: "Enter" });

    await waitFor(() => {
      expect(engine.bodies).toEqual([
        { route: "accept", body: { transaction_ids: [12] } },
        { route: "patch", body: { category_id: 5 } },
      ]);
    });
    // Only the skipped one is left.
    expect(await screen.findByRole("heading", { name: "That's all for now" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review the skipped ones" }));
    expect(await screen.findByRole("heading", { name: "Corner Bakery" })).toBeInTheDocument();
  });

  it("can't accept when there is no suggestion", async () => {
    const engine = reviewEngine([mystery]);
    renderScreen(engine);
    await screen.findByRole("heading", { name: "Mystery Shop" });

    expect(screen.getByText(/No suggestion/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
    press("a");
    expect(engine.bodies).toEqual([]);
    expect(screen.queryByRole("button", { name: /Accept all/ })).not.toBeInTheDocument();
  });

  it("ignores shortcuts while typing", async () => {
    const engine = reviewEngine([bakery]);
    renderScreen(engine);
    await screen.findByRole("heading", { name: "Corner Bakery" });
    const input = document.createElement("input");
    document.body.append(input);

    fireEvent.keyDown(input, { key: "a" });
    fireEvent.keyDown(document.body, { key: "a", ctrlKey: true });

    expect(engine.bodies).toEqual([]);
    input.remove();
  });

  it("accepts every suggestion after confirming", async () => {
    const engine = reviewEngine([bakery, books, mystery]);
    renderScreen(engine);
    await screen.findByRole("heading", { name: "Corner Bakery" });

    fireEvent.click(screen.getByRole("button", { name: /Accept all 2 suggestions/ }));
    const dialog = await screen.findByRole("alertdialog", { name: "Accept all 2 suggestions?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Accept all" }));

    expect(await screen.findByText("Accepted 2 suggestions")).toBeInTheDocument();
    expect(engine.bodies).toEqual([{ route: "accept-all", body: {} }]);
    expect(await screen.findByRole("heading", { name: "Mystery Shop" })).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("brings the transaction back and says why when accepting fails", async () => {
    renderScreen(
      reviewEngine([bakery, books], {
        "POST /review/accept": () =>
          Response.json({ detail: "The database is locked." }, { status: 503 }),
      }),
    );
    await screen.findByRole("heading", { name: "Corner Bakery" });

    press("a");

    expect(await screen.findByText("Couldn't accept the suggestion")).toBeInTheDocument();
    expect(screen.getByText("The database is locked.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Corner Bakery" })).toBeInTheDocument();
  });

  it("says when everything is reviewed", async () => {
    renderScreen(reviewEngine([]));

    expect(await screen.findByRole("heading", { name: "All caught up" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Accept all/ })).not.toBeInTheDocument();
  });

  it("shows an error with a retry when the queue can't be loaded", async () => {
    renderScreen(
      reviewEngine([bakery], {
        "GET /transactions": () =>
          Response.json({ detail: "The database is locked." }, { status: 503 }),
      }),
    );

    expect(await screen.findByText("The database is locked.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { queryKeys } from "@/api/queries";
import { AppLayout } from "@/components/AppLayout";
import { paths } from "@/paths";
import { STATUS_POLL_MS, type CategorizationStatus } from "@/screens/review/queries";
import { makeCategorizationStatus } from "@/test/fixtures";
import { renderWithApi } from "@/test/renderWithApi";

function renderLayout(status: CategorizationStatus | (() => CategorizationStatus), waiting = 0) {
  return renderWithApi(<AppLayout />, {
    path: paths.transactions,
    routes: {
      "GET /review/summary": { waiting, with_suggestion: 0 },
      "GET /categorization/status": () =>
        Response.json(typeof status === "function" ? status() : status),
    },
  });
}

function requestsTo(fetchMock: ReturnType<typeof renderLayout>["fetchMock"], path: string) {
  return fetchMock.mock.calls.filter(([request]) => new URL(request.url).pathname === path);
}

describe("AppLayout", () => {
  it("links every screen, with the review queue's count", async () => {
    renderLayout(makeCategorizationStatus(), 7);

    const nav = screen.getByRole("navigation", { name: "Main" });
    const review = within(nav).getByRole("link", { name: /^Review/ });
    await waitFor(() => {
      expect(review).toHaveAccessibleName("Review, 7 waiting");
    });
    expect(review).toHaveAttribute("href", paths.review);
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href")),
    ).toEqual([
      paths.transactions,
      paths.review,
      paths.import,
      paths.accounts,
      paths.rules,
      paths.settings,
    ]);
  });

  it("shows no count when nothing waits for review", async () => {
    const { fetchMock } = renderLayout(makeCategorizationStatus(), 0);

    await waitFor(() => {
      expect(requestsTo(fetchMock, "/review/summary")).toHaveLength(1);
    });
    expect(screen.getByRole("link", { name: "Review" })).toBeInTheDocument();
  });

  it("shows the progress of a background run", async () => {
    renderLayout(makeCategorizationStatus({ state: "running", processed: 128, total: 640 }));

    expect(await screen.findByText("Categorizing 128 of 640…")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Categorizing transactions" });
    expect(bar).toHaveAttribute("aria-valuenow", "128");
    expect(bar).toHaveAttribute("aria-valuemax", "640");
  });

  it("stays quiet when idle or when a run has nothing to do", async () => {
    const { fetchMock } = renderLayout(makeCategorizationStatus({ state: "queued", total: 0 }));

    await waitFor(() => {
      expect(requestsTo(fetchMock, "/categorization/status")).toHaveLength(1);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("mentions a problem in the last run", async () => {
    renderLayout(
      makeCategorizationStatus({
        last_error: "Some categorization steps failed and were skipped.",
      }),
    );

    expect(
      await screen.findByRole("button", { name: "Categorization had a problem" }),
    ).toBeInTheDocument();
  });

  it("polls while a run is going and refreshes the transactions when it ends", async () => {
    let status = makeCategorizationStatus({ state: "running", processed: 1, total: 2 });
    const { fetchMock } = renderLayout(() => status);
    await screen.findByText("Categorizing 1 of 2…");
    const summaries = requestsTo(fetchMock, "/review/summary").length;

    status = makeCategorizationStatus({ runs_finished: 2 });

    await waitFor(
      () => {
        expect(screen.queryByText(/Categorizing/)).not.toBeInTheDocument();
      },
      { timeout: STATUS_POLL_MS * 3 },
    );
    // The review count (one of the transaction views) was fetched again.
    await waitFor(() => {
      expect(requestsTo(fetchMock, "/review/summary").length).toBeGreaterThan(summaries);
    });
  });

  it("checks the status again when transactions change, e.g. after an import", async () => {
    const { fetchMock, queryClient } = renderLayout(makeCategorizationStatus());
    await waitFor(() => {
      expect(requestsTo(fetchMock, "/categorization/status")).toHaveLength(1);
    });

    await act(() => queryClient.invalidateQueries({ queryKey: queryKeys.transactions }));

    expect(requestsTo(fetchMock, "/categorization/status")).toHaveLength(2);
  });
});

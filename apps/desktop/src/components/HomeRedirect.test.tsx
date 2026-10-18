import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HomeRedirect } from "@/components/HomeRedirect";
import { paths } from "@/paths";
import { renderWithApi } from "@/test/renderWithApi";

const destinations = [
  { path: paths.welcome, element: <p>Onboarding</p> },
  { path: paths.transactions, element: <p>Transactions</p> },
];

describe("HomeRedirect", () => {
  it("sends a new user to onboarding", async () => {
    renderWithApi(<HomeRedirect />, {
      routes: { "GET /accounts": [] },
      extraRoutes: destinations,
    });

    expect(await screen.findByText("Onboarding")).toBeInTheDocument();
  });

  it("sends a returning user to their transactions", async () => {
    renderWithApi(<HomeRedirect />, {
      routes: {
        "GET /accounts": [
          { id: 1, name: "Checking", institution: null, type: "checking", currency: "CAD" },
        ],
      },
      extraRoutes: destinations,
    });

    expect(await screen.findByText("Transactions")).toBeInTheDocument();
  });

  it("shows a retryable error if accounts can't be loaded", async () => {
    renderWithApi(<HomeRedirect />, {
      routes: {
        "GET /accounts": () => Response.json({ detail: "Database locked." }, { status: 503 }),
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Database locked.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

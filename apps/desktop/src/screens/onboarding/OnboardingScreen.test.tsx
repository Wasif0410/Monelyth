import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/api/queries";
import { paths } from "@/paths";
import { OnboardingScreen } from "@/screens/onboarding/OnboardingScreen";
import { renderWithApi, type StubRoutes } from "@/test/renderWithApi";

const ACCOUNT = { id: 1, name: "Everyday", institution: null, type: "checking", currency: "CAD" };
const DEMO_RESULT = {
  accounts: [
    { id: 1, name: "Demo Checking", institution: null, type: "checking", currency: "EUR" },
    { id: 2, name: "Demo Visa", institution: null, type: "credit_card", currency: "EUR" },
  ],
  imports: [],
  transactions_added: 612,
};

const destinations = [
  { path: paths.transactions, element: <p>Transactions screen</p> },
  { path: paths.import, element: <p>Import screen</p> },
];

function renderOnboarding(routes: StubRoutes = {}) {
  return renderWithApi(<OnboardingScreen />, {
    path: paths.welcome,
    routes: { "GET /accounts": [], ...routes },
    extraRoutes: destinations,
  });
}

function setLanguages(languages: string[]) {
  vi.spyOn(navigator, "languages", "get").mockReturnValue(languages);
}

/** Pick an option in a Radix select with the keyboard and a click, as jsdom allows. */
function choose(combobox: HTMLElement, option: string) {
  fireEvent.keyDown(combobox, { key: "Enter" });
  fireEvent.click(screen.getByRole("option", { name: option }));
}

async function jsonBody(request: Request): Promise<unknown> {
  return JSON.parse(await request.text()) as unknown;
}

beforeEach(() => {
  setLanguages(["en-CA"]);
  // Radix Select scrolls the chosen option into view and tracks pointer capture, which jsdom
  // does not implement.
  Element.prototype.scrollIntoView = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn(() => false);
  Element.prototype.releasePointerCapture = vi.fn();
});

describe("OnboardingScreen", () => {
  it("welcomes the user with the privacy promise", async () => {
    const { fetchMock } = renderOnboarding();

    expect(screen.getByRole("heading", { level: 1, name: "Welcome to Monelyth" })).toBeVisible();
    const promises = within(screen.getByRole("list", { name: "Privacy" })).getAllByRole("listitem");
    expect(promises.map((item) => item.textContent)).toEqual([
      expect.stringContaining("Your data never leaves this computer"),
      expect.stringContaining("No account or sign-up"),
      expect.stringContaining("AI that runs locally"),
    ]);
    // With no accounts yet there is nowhere else to go.
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    expect(screen.queryByRole("link", { name: "Go to my transactions" })).toBeNull();
  });

  it("preselects the currency of the user's region", () => {
    renderOnboarding();

    expect(screen.getByRole("combobox", { name: "Currency" })).toHaveTextContent(
      "Canadian Dollar (CAD)",
    );
  });

  it("falls back to US dollars when the region's currency isn't offered", () => {
    setLanguages(["ja-JP"]);
    renderOnboarding();

    expect(screen.getByRole("combobox", { name: "Currency" })).toHaveTextContent("US Dollar (USD)");
  });

  it("adds demo data, refreshes the data and opens the transactions", async () => {
    let respond: (response: Response) => void = () => undefined;
    const sent: unknown[] = [];
    const { queryClient } = renderOnboarding({
      "POST /demo": async (request: Request) => {
        sent.push(await jsonBody(request));
        return new Promise<Response>((resolve) => {
          respond = resolve;
        });
      },
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    choose(screen.getByRole("combobox", { name: "Currency" }), "Euro (EUR)");
    fireEvent.click(screen.getByRole("button", { name: /Explore with demo data/ }));

    const progress = await screen.findByRole("button", { name: /Adding demo data/ });
    expect(progress).toBeDisabled();
    expect(screen.getByRole("button", { name: /Import my own statement/ })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Adding demo data");
    await waitFor(() => {
      expect(sent).toEqual([{ currency: "EUR" }]);
    });

    respond(Response.json(DEMO_RESULT, { status: 201 }));

    expect(await screen.findByText("Transactions screen")).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.accounts });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.transactions });
  });

  it("shows the engine's message when demo data can't be added", async () => {
    renderOnboarding({
      "POST /demo": () =>
        Response.json(
          { detail: "The demo data has already been added: look for Demo Checking." },
          { status: 409 },
        ),
    });

    fireEvent.click(screen.getByRole("button", { name: /Explore with demo data/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The demo data has already been added: look for Demo Checking.",
    );
    expect(screen.getByRole("button", { name: /Explore with demo data/ })).toBeEnabled();
    expect(screen.queryByText("Transactions screen")).toBeNull();
  });

  it("creates the first account and opens the import", async () => {
    const sent: unknown[] = [];
    renderOnboarding({
      "POST /accounts": async (request: Request) => {
        sent.push(await jsonBody(request));
        return Response.json({ ...ACCOUNT, type: "savings" }, { status: 201 });
      },
    });

    fireEvent.click(screen.getByRole("button", { name: /Import my own statement/ }));

    const name = screen.getByRole("textbox", { name: "Account name" });
    expect(name).toHaveFocus();
    expect(screen.getByRole("combobox", { name: "Type" })).toHaveTextContent("Checking");
    expect(screen.getByRole("combobox", { name: "Currency" })).toHaveTextContent(
      "Canadian Dollar (CAD)",
    );

    fireEvent.change(name, { target: { value: "  Everyday  " } });
    choose(screen.getByRole("combobox", { name: "Type" }), "Savings");
    fireEvent.click(screen.getByRole("button", { name: "Add account and import" }));

    expect(await screen.findByText("Import screen")).toBeInTheDocument();
    expect(sent).toEqual([{ name: "Everyday", type: "savings", currency: "CAD" }]);
  });

  it("asks for a name before creating the account", () => {
    const { fetchMock } = renderOnboarding();

    fireEvent.click(screen.getByRole("button", { name: /Import my own statement/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add account and import" }));

    const name = screen.getByRole("textbox", { name: "Account name" });
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription(/Give the account a name/);
    expect(fetchMock.mock.calls.map(([request]) => request.method)).not.toContain("POST");
  });

  it("shows the engine's message when the account can't be created", async () => {
    renderOnboarding({
      "POST /accounts": () =>
        Response.json({ detail: "Currency must be a three-letter code." }, { status: 422 }),
    });

    fireEvent.click(screen.getByRole("button", { name: /Import my own statement/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Account name" }), {
      target: { value: "Everyday" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add account and import" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Currency must be a three-letter code.",
    );
    expect(screen.getByRole("button", { name: "Add account and import" })).toBeEnabled();
    expect(screen.queryByText("Import screen")).toBeNull();
  });

  it("goes back from the account form to the choices", () => {
    renderOnboarding();

    fireEvent.click(screen.getByRole("button", { name: /Import my own statement/ }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByRole("button", { name: /Import my own statement/ })).toHaveFocus();
    expect(screen.queryByRole("textbox", { name: "Account name" })).toBeNull();
  });

  it("lets a user who already has accounts leave", async () => {
    renderOnboarding({ "GET /accounts": [ACCOUNT] });

    fireEvent.click(await screen.findByRole("link", { name: "Go to my transactions" }));

    expect(await screen.findByText("Transactions screen")).toBeInTheDocument();
  });
});

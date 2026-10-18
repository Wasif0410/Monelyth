import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast, Toaster } from "sonner";
import { afterEach, describe, expect, it } from "vitest";

import { paths } from "@/paths";
import { reviewKeys } from "@/screens/review/queries";
import type { Rule } from "@/screens/rules/queries";
import { RulesScreen } from "@/screens/rules/RulesScreen";
import { categories } from "@/screens/transactions/testData";
import { makeCategorizationStatus, makeRule } from "@/test/fixtures";
import { renderWithApi, type StubRoutes } from "@/test/renderWithApi";

afterEach(() => {
  // Sonner keeps toasts in a module-wide store; don't let one leak into the next test.
  toast.dismiss();
});

const mine = makeRule({ id: 200, pattern: "corner bakery", category_id: 6, priority: 3 });
const builtIn = [
  makeRule({ id: 1, pattern: "uber eats", category_id: 6, priority: 20, created_by: "system" }),
  makeRule({ id: 2, pattern: "payroll", category_id: 1, priority: 10, created_by: "system" }),
];

/** An engine whose rule list reflects what the screen changes. */
function rulesEngine(initial: readonly Rule[], overrides: StubRoutes = {}) {
  let rules = [...initial];
  const requests: { route: string; body: unknown }[] = [];
  const record = async (route: string, request: Request) => {
    const body: unknown = request.method === "DELETE" ? null : await request.json();
    requests.push({ route, body });
    return body;
  };
  const routes: StubRoutes = {
    "GET /categories": categories,
    "GET /rules": () => Response.json(rules),
    "POST /rules/preview": async (request: Request) => {
      const { pattern } = (await record("preview", request)) as { pattern: string };
      return Response.json(
        pattern.includes("(")
          ? { detail: "That isn't a valid regular expression: missing ), unterminated subpattern." }
          : { matching: 2, user_set: 1, examples: ["Uber"] },
        { status: pattern.includes("(") ? 422 : 200 },
      );
    },
    "POST /rules": async (request: Request) => {
      const body = (await record("create", request)) as Omit<Rule, "id" | "created_by">;
      const created = makeRule({ ...body, id: 201 });
      rules = [created, ...rules];
      return Response.json(created, { status: 201 });
    },
    [`PATCH /rules/${String(mine.id)}`]: async (request: Request) => {
      const body = (await record("update", request)) as Partial<Rule>;
      rules = rules.map((rule) => (rule.id === mine.id ? { ...rule, ...body } : rule));
      return Response.json(rules.find((rule) => rule.id === mine.id));
    },
    [`DELETE /rules/${String(mine.id)}`]: async (request: Request) => {
      await record("delete", request);
      rules = rules.filter((rule) => rule.id !== mine.id);
      return new Response(null, { status: 204 });
    },
    ...overrides,
  };
  return { routes, requests };
}

function renderScreen(engine: ReturnType<typeof rulesEngine>) {
  return renderWithApi(
    <>
      <RulesScreen />
      <Toaster />
    </>,
    { path: paths.rules, routes: engine.routes },
  );
}

/** Open a Radix select with the keyboard and choose an option, as a keyboard user would. */
async function choose(trigger: HTMLElement, option: string) {
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "Enter" });
  const item = await screen.findByRole("option", { name: option });
  fireEvent.keyDown(item, { key: "Enter" });
}

describe("RulesScreen", () => {
  it("lists the user's rules, then the built-in ones", async () => {
    renderScreen(rulesEngine([mine, ...builtIn]));

    const yours = await screen.findByRole("table", { name: "Your rules" });
    const row = within(yours).getByText("corner bakery").closest("tr");
    if (!row) throw new Error("No row for corner bakery");
    expect(within(row).getByText("Contains the words")).toBeInTheDocument();
    expect(within(row).getByText("Dining Out")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();
    expect(
      within(row).getByRole("button", { name: "Edit the rule for corner bakery" }),
    ).toBeInTheDocument();

    const defaults = screen.getByRole("table", { name: "Built-in rules" });
    expect(within(defaults).getByText("uber eats")).toBeInTheDocument();
    expect(within(defaults).getByText("Salary")).toBeInTheDocument();
    expect(within(defaults).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/Categories you set yourself never change/)).toBeInTheDocument();
  });

  it("explains rules before the user has any, and searches the built-in ones", async () => {
    renderScreen(rulesEngine(builtIn));

    expect(await screen.findByText(/You haven't made any rules yet/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search built-in rules" }), {
      target: { value: "salary" },
    });
    const defaults = screen.getByRole("table", { name: "Built-in rules" });
    expect(within(defaults).getByText("payroll")).toBeInTheDocument();
    expect(within(defaults).queryByText("uber eats")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: "Search built-in rules" }), {
      target: { value: "zzz" },
    });
    expect(screen.getByText("No built-in rule matches “zzz”.")).toBeInTheDocument();
  });

  it("adds a rule, showing what it matches while typing", async () => {
    const engine = rulesEngine(builtIn);
    const { queryClient } = renderScreen(engine);
    // As the app layout keeps it, so the screen can be seen asking for it again.
    queryClient.setQueryData(reviewKeys.categorization, makeCategorizationStatus());
    await screen.findByRole("table", { name: "Built-in rules" });
    fireEvent.click(screen.getByRole("button", { name: "Add rule" }));
    const dialog = await screen.findByRole("dialog", { name: "Add rule" });

    expect(within(dialog).getByText(/Matches whole words/)).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Look for"), { target: { value: "uber" } });
    expect(
      await within(dialog).findByText(
        "Matches 2 transactions, such as Uber. 1 transaction you categorized yourself keeps its category.",
      ),
    ).toBeInTheDocument();
    expect(engine.requests).toEqual([
      { route: "preview", body: { pattern: "uber", match_type: "contains" } },
    ]);

    const save = within(dialog).getByRole("button", { name: "Add rule" });
    expect(save).toBeDisabled();
    await choose(within(dialog).getByRole("combobox", { name: "Category" }), "Groceries");
    fireEvent.change(within(dialog).getByLabelText("Priority"), { target: { value: "5" } });
    fireEvent.click(save);

    expect(await screen.findByText("Rule added")).toBeInTheDocument();
    expect(engine.requests.filter(({ route }) => route === "create")).toEqual([
      {
        route: "create",
        body: { pattern: "uber", match_type: "contains", category_id: 5, priority: 5 },
      },
    ]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      await within(screen.getByRole("table", { name: "Your rules" })).findByText("uber"),
    ).toBeInTheDocument();
    // A rule change re-categorizes in the background: the status is checked again.
    await waitFor(() => {
      expect(queryClient.getQueryState(reviewKeys.categorization)?.isInvalidated).toBe(true);
    });
  });

  it("shows why a pattern can't be used, and why saving failed", async () => {
    const engine = rulesEngine(builtIn, {
      "POST /rules": () =>
        Response.json(
          { detail: "You already have a rule for “uber”. Edit that one instead." },
          { status: 409 },
        ),
    });
    renderScreen(engine);
    await screen.findByRole("table", { name: "Built-in rules" });
    fireEvent.click(screen.getByRole("button", { name: "Add rule" }));
    const dialog = await screen.findByRole("dialog", { name: "Add rule" });
    await choose(within(dialog).getByRole("combobox", { name: "Match" }), "Regular expression");

    fireEvent.change(within(dialog).getByLabelText("Look for"), { target: { value: "uber(" } });
    expect(
      await within(dialog).findByText(
        "That isn't a valid regular expression: missing ), unterminated subpattern.",
      ),
    ).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Look for"), { target: { value: "uber" } });
    await choose(within(dialog).getByRole("combobox", { name: "Category" }), "Groceries");
    fireEvent.click(within(dialog).getByRole("button", { name: "Add rule" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "You already have a rule for “uber”. Edit that one instead.",
    );
  });

  it("edits one of the user's rules", async () => {
    const engine = rulesEngine([mine, ...builtIn]);
    renderScreen(engine);
    fireEvent.click(await screen.findByRole("button", { name: "Edit the rule for corner bakery" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit rule" });
    expect(within(dialog).getByLabelText("Look for")).toHaveValue("corner bakery");
    expect(within(dialog).getByLabelText("Priority")).toHaveValue(3);

    await choose(within(dialog).getByRole("combobox", { name: "Category" }), "Groceries");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save rule" }));

    expect(await screen.findByText("Rule saved")).toBeInTheDocument();
    expect(engine.requests.filter(({ route }) => route === "update")).toEqual([
      {
        route: "update",
        body: { pattern: "corner bakery", match_type: "contains", category_id: 5, priority: 3 },
      },
    ]);
  });

  it("refuses a priority outside 0 to 1000", async () => {
    renderScreen(rulesEngine([mine, ...builtIn]));
    fireEvent.click(await screen.findByRole("button", { name: "Edit the rule for corner bakery" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit rule" });

    fireEvent.change(within(dialog).getByLabelText("Priority"), { target: { value: "1001" } });

    expect(within(dialog).getByLabelText("Priority")).toHaveAttribute("aria-invalid", "true");
    expect(within(dialog).getByRole("button", { name: "Save rule" })).toBeDisabled();
  });

  it("deletes one of the user's rules after confirming", async () => {
    const engine = rulesEngine([mine, ...builtIn]);
    renderScreen(engine);
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete the rule for corner bakery" }),
    );
    const dialog = await screen.findByRole("alertdialog", {
      name: "Delete the rule for “corner bakery”?",
    });
    expect(within(dialog).getByText(/Categories you set yourself stay/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Delete rule" }));

    expect(await screen.findByText("Rule deleted")).toBeInTheDocument();
    expect(engine.requests).toEqual([{ route: "delete", body: null }]);
    expect(await screen.findByText(/You haven't made any rules yet/)).toBeInTheDocument();
  });

  it("shows an error with a retry when the rules can't be loaded", async () => {
    renderScreen(
      rulesEngine([], {
        "GET /rules": () => Response.json({ detail: "The database is locked." }, { status: 503 }),
      }),
    );

    expect(await screen.findByText("The database is locked.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

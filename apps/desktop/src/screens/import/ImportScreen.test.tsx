import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Schemas } from "@/api/client";
import type { Account } from "@/api/queries";
import { formatMoney } from "@/lib/format";
import { paths } from "@/paths";
import { ImportScreen } from "@/screens/import/ImportScreen";
import { makeAccount } from "@/test/fixtures";
import { renderWithApi, type StubRoutes } from "@/test/renderWithApi";

type Preview = Schemas["ImportPreviewOut"];
type Layout = Schemas["CsvLayoutOut"];

const CHECKING: Account = makeAccount({ id: 1, name: "Main Checking" });

const LAYOUT: Layout = {
  version: 1,
  encoding: "utf-8-sig",
  delimiter: ",",
  skip_rows: 0,
  has_header: true,
  date_column: 0,
  description_column: 1,
  amount: { kind: "signed", column: 2 },
  date_format: "%Y-%m-%d",
  decimal_separator: ".",
  invert_signs: false,
};

const DATE_FORMATS = [
  { code: "%Y-%m-%d", label: "YYYY-MM-DD" },
  { code: "%m/%d/%Y", label: "MM/DD/YYYY" },
  { code: "%d/%m/%Y", label: "DD/MM/YYYY" },
];

const ROWS: Preview["rows"] = [
  {
    posted_date: "2026-09-01",
    description: "SQ *BLUE BOTTLE 0423 TORONTO ON",
    merchant: "Blue Bottle",
    amount_cents: -450,
  },
  {
    posted_date: "2026-09-02",
    description: "PAYROLL DEPOSIT ACME CORP",
    merchant: "Acme Corp",
    amount_cents: 120000,
  },
];

function csvPreview(overrides: Partial<Preview> = {}, csv: Partial<Preview["csv"]> = {}): Preview {
  return {
    format: "csv",
    file_name: "september.csv",
    rows: ROWS,
    transaction_count: 84,
    currency: null,
    warnings: [],
    previous_import: null,
    csv: {
      layout: LAYOUT,
      layout_source: "detected",
      columns: ["Date", "Description", "Amount"],
      questions: [],
      date_formats: DATE_FORMATS,
      ...csv,
    },
    ...overrides,
  };
}

const RESULT: Schemas["ImportResultOut"] = {
  import_id: 7,
  account_id: 1,
  file_name: "september.csv",
  format: "csv",
  added: 84,
  skipped_duplicates: 12,
  warnings: ["Skipped 1 blank row."],
};

function statementFile(
  name = "september.csv",
  content = "Date,Description,Amount\n2026-09-01,COFFEE,-4.50\n",
): File {
  return new File([content], name, { type: "text/csv" });
}

/**
 * fetch and Request in the test environment are Node's, which can't serialize jsdom's FormData
 * and File (a browser has one consistent set). This Request keeps the FormData the screen built,
 * so the stubbed engine can check exactly what was sent.
 */
class FormRecordingRequest extends Request {
  readonly form: FormData | null;

  constructor(input: RequestInfo | URL, init?: RequestInit) {
    const form = init?.body instanceof FormData ? init.body : null;
    super(input, form === null ? init : { ...init, body: null });
    this.form = form;
  }
}

/** A handler that records each multipart request body and answers with `respond`. */
function multipartRoute(respond: (form: FormData) => Response) {
  const bodies: FormData[] = [];
  const handler = (request: Request) => {
    const { form } = request as FormRecordingRequest;
    if (form === null) throw new Error("Expected a multipart request");
    bodies.push(form);
    return respond(form);
  };
  return { handler, bodies };
}

function renderScreen(routes: StubRoutes) {
  return renderWithApi(<ImportScreen />, {
    routes,
    path: paths.import,
    extraRoutes: [{ path: paths.transactions, element: <p>Transactions page</p> }],
  });
}

function chooseFile(file: File) {
  fireEvent.change(screen.getByLabelText("Statement file"), { target: { files: [file] } });
}

/** Open a Radix select by keyboard and pick an option. */
async function choose(label: string, option: string | RegExp) {
  fireEvent.keyDown(screen.getByRole("combobox", { name: label }), { key: "Enter" });
  fireEvent.click(await screen.findByRole("option", { name: option }));
}

/** A button once it can be clicked, e.g. Import once accounts have loaded. */
async function enabledButton(name: string) {
  const button = await screen.findByRole("button", { name });
  await waitFor(() => {
    expect(button).toBeEnabled();
  });
  return button;
}

function layoutSent(form: FormData): unknown {
  const layout = form.get("layout");
  return typeof layout === "string" ? JSON.parse(layout) : null;
}

beforeEach(() => {
  // Unstubbed after each test by the `unstubGlobals` setting.
  vi.stubGlobal("Request", FormRecordingRequest);
});

describe("ImportScreen", () => {
  it("previews a chosen file", async () => {
    const preview = multipartRoute(() => Response.json(csvPreview()));
    renderScreen({ "GET /accounts": [CHECKING], "POST /imports/preview": preview.handler });

    expect(screen.getByRole("button", { name: "Choose file" })).toBeInTheDocument();
    chooseFile(statementFile());

    expect(await screen.findByText("Blue Bottle")).toBeInTheDocument();
    expect(screen.getByText("september.csv")).toBeInTheDocument();
    expect(screen.getByText("CSV")).toBeInTheDocument();
    expect(screen.getByText("84 transactions")).toBeInTheDocument();
    expect(screen.getByText("SQ *BLUE BOTTLE 0423 TORONTO ON")).toBeInTheDocument();
    // The only account is preselected, so amounts show in its currency.
    expect(await screen.findByText(formatMoney(-450, "CAD"))).toBeInTheDocument();
    expect(screen.getByText(formatMoney(120000, "CAD"))).toHaveClass("text-success");
    expect(screen.getByRole("button", { name: "Import 84 transactions" })).toBeEnabled();

    const [sent] = preview.bodies;
    expect((sent?.get("file") as File | null)?.name).toBe("september.csv");
    expect(sent?.has("layout")).toBe(false);
  });

  it("shows the file's warnings", async () => {
    renderScreen({
      "GET /accounts": [CHECKING],
      "POST /imports/preview": csvPreview({ warnings: ['Skipped row 9: "Total".'] }),
    });

    chooseFile(statementFile());

    expect(await screen.findByRole("list", { name: "Notes about this file" })).toHaveTextContent(
      'Skipped row 9: "Total".',
    );
  });

  it("asks about the layout and previews again as the user answers", async () => {
    const question = 'Dates such as "03/04/2026" could be read as MM/DD/YYYY or DD/MM/YYYY.';
    const preview = multipartRoute((form) =>
      form.has("layout")
        ? Response.json(
            csvPreview(
              { transaction_count: 2 },
              { layout: { ...LAYOUT, date_format: "%d/%m/%Y" }, layout_source: "chosen" },
            ),
          )
        : Response.json(
            csvPreview(
              { rows: [], transaction_count: null },
              {
                layout: { ...LAYOUT, date_format: null },
                questions: [
                  {
                    kind: "date_order_ambiguous",
                    message: question,
                    options: ["%m/%d/%Y", "%d/%m/%Y"],
                  },
                ],
              },
            ),
          ),
    );
    renderScreen({ "GET /accounts": [CHECKING], "POST /imports/preview": preview.handler });

    chooseFile(statementFile());

    expect(await screen.findByText(question)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Date column" })).toHaveTextContent("Date");
    expect(screen.getByRole("combobox", { name: "Description column" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Amount column" })).toHaveTextContent("Amount");
    expect(screen.getByRole("combobox", { name: "Purchases are shown as" })).toBeInTheDocument();
    expect(
      screen.getByText("Choose the date format above to see the transactions."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();

    await choose("Date format", "DD/MM/YYYY");

    expect(await screen.findByText("Blue Bottle")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Import 2 transactions" })).toBeEnabled();
    });
    expect(preview.bodies).toHaveLength(2);
    expect(layoutSent(preview.bodies[1] ?? new FormData())).toEqual({
      ...LAYOUT,
      date_format: "%d/%m/%Y",
    });
  });

  it("switches to debit and credit columns", async () => {
    const preview = multipartRoute((form) =>
      Response.json(
        csvPreview(form.has("layout") ? { transaction_count: 3 } : {}, {
          columns: ["Date", "Description", "Debit", "Credit"],
        }),
      ),
    );
    renderScreen({ "GET /accounts": [CHECKING], "POST /imports/preview": preview.handler });
    chooseFile(statementFile());
    await screen.findByText("Blue Bottle");

    await choose("Amounts", "In money-out and money-in columns");
    expect(
      screen.queryByRole("combobox", { name: "Purchases are shown as" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Choose the money-in column above to see the transactions."),
    ).toBeInTheDocument();
    await choose("Money-in column", "Credit");

    await waitFor(() => {
      expect(preview.bodies).toHaveLength(2);
    });
    expect(layoutSent(preview.bodies[1] ?? new FormData())).toMatchObject({
      amount: { kind: "debit_credit", debit_column: 2, credit_column: 3 },
      invert_signs: false,
    });
    expect(await screen.findByRole("button", { name: "Import 3 transactions" })).toBeEnabled();
  });

  it("explains a layout that doesn't fit the file", async () => {
    const preview = multipartRoute((form) =>
      form.has("layout")
        ? Response.json(
            { detail: 'Row 2: the date "2026-09-01" doesn\'t match the format DD/MM/YYYY.' },
            { status: 422 },
          )
        : Response.json(csvPreview()),
    );
    renderScreen({ "GET /accounts": [CHECKING], "POST /imports/preview": preview.handler });
    chooseFile(statementFile());
    await screen.findByText("Blue Bottle");

    await choose("Date format", "DD/MM/YYYY");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("These choices don't fit the file");
    expect(alert).toHaveTextContent(
      'Row 2: the date "2026-09-01" doesn\'t match the format DD/MM/YYYY.',
    );
    expect(screen.queryByText("Blue Bottle")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
  });

  it("keeps a saved layout out of the way", async () => {
    renderScreen({
      "GET /accounts": [CHECKING],
      "POST /imports/preview": csvPreview({}, { layout_source: "saved" }),
    });

    chooseFile(statementFile());

    expect(
      await screen.findByText("Using the layout you confirmed for this bank."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Date column" })).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Change columns" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByRole("combobox", { name: "Date column" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide columns" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("warns that a file was imported before and won't import it again", async () => {
    renderScreen({
      "GET /accounts": [CHECKING],
      "POST /imports/preview": csvPreview({
        previous_import: {
          id: 3,
          account_id: 1,
          file_name: "september.csv",
          imported_at: "2026-10-03T15:00:00Z",
        },
      }),
    });

    chooseFile(statementFile());

    // The account's name appears once accounts have loaded.
    await screen.findByText(/It went into Main Checking\./);
    const notice = screen.getByRole("alert");
    const date = new Date("2026-10-03T15:00:00Z").toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
    expect(notice).toHaveTextContent(`You imported this file on ${date}`);
    expect(notice).toHaveTextContent("It went into Main Checking.");
    expect(screen.getByRole("button", { name: "Import 84 transactions" })).toBeDisabled();
  });

  it("creates an account from the dialog and selects it", async () => {
    const accounts: Account[] = [];
    let createdBody: unknown = null;
    renderScreen({
      "GET /accounts": () => Response.json(accounts),
      "POST /accounts": async (request: Request) => {
        createdBody = await request.json();
        const account: Account = makeAccount({ id: 5, name: "Everyday", type: "savings" });
        accounts.push(account);
        return Response.json(account, { status: 201 });
      },
      "POST /imports/preview": csvPreview(),
    });
    chooseFile(statementFile());
    await screen.findByText("Blue Bottle");

    fireEvent.click(await screen.findByRole("button", { name: "New account…" }));
    const dialog = await screen.findByRole("dialog", { name: "New account" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create account" }));
    expect(within(dialog).getByText("Enter a name, such as “Main Checking”.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Currency")).toHaveAttribute("aria-invalid", "true");

    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "  Everyday " } });
    await choose("Type", "Savings");
    fireEvent.change(within(dialog).getByLabelText("Currency"), { target: { value: "cad" } });
    expect(within(dialog).getByLabelText("Currency")).toHaveValue("CAD");
    fireEvent.click(within(dialog).getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(createdBody).toEqual({ name: "Everyday", type: "savings", currency: "CAD" });
    expect(screen.getByRole("combobox", { name: "Import into" })).toHaveTextContent("Everyday");
    expect(screen.getByRole("button", { name: "Import 84 transactions" })).toBeEnabled();
  });

  it("shows an error from creating an account in the dialog", async () => {
    renderScreen({
      "GET /accounts": [],
      "POST /accounts": () =>
        Response.json({ detail: "The database is read-only." }, { status: 503 }),
      "POST /imports/preview": csvPreview(),
    });
    chooseFile(statementFile());

    fireEvent.click(await screen.findByRole("button", { name: "New account…" }));
    const dialog = await screen.findByRole("dialog", { name: "New account" });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Everyday" } });
    fireEvent.change(within(dialog).getByLabelText("Currency"), { target: { value: "CAD" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create account" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The database is read-only.",
    );
  });

  it("imports the file and summarizes what was added", async () => {
    const commit = multipartRoute(() => Response.json(RESULT, { status: 201 }));
    const { queryClient, router } = renderScreen({
      "GET /accounts": [CHECKING],
      "POST /imports/preview": csvPreview(),
      "POST /imports": commit.handler,
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    chooseFile(statementFile());

    fireEvent.click(await enabledButton("Import 84 transactions"));

    const heading = await screen.findByRole("heading", {
      name: "Added 84 transactions, skipped 12 duplicates",
    });
    expect(heading).toHaveFocus();
    expect(screen.getByText("From september.csv into Main Checking.")).toBeInTheDocument();
    expect(screen.getByText("Skipped 1 blank row.")).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["transactions"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["accounts"] });

    const [sent] = commit.bodies;
    expect(sent?.get("account_id")).toBe("1");
    expect((sent?.get("file") as File | null)?.name).toBe("september.csv");
    expect(layoutSent(sent ?? new FormData())).toEqual(LAYOUT);

    fireEvent.click(screen.getByRole("button", { name: "View transactions" }));
    expect(await screen.findByText("Transactions page")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(paths.transactions);
  });

  it("starts over from the summary", async () => {
    renderScreen({
      "GET /accounts": [CHECKING],
      "POST /imports/preview": csvPreview(),
      "POST /imports": () => Response.json({ ...RESULT, added: 0, warnings: [] }, { status: 201 }),
    });
    chooseFile(statementFile());
    fireEvent.click(await enabledButton("Import 84 transactions"));

    expect(
      await screen.findByRole("heading", { name: "No new transactions: skipped 12 duplicates" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import another file" }));

    expect(screen.getByRole("region", { name: "Choose a statement" })).toBeInTheDocument();
  });

  it("shows an engine error from the import inline", async () => {
    renderScreen({
      "GET /accounts": [CHECKING],
      "POST /imports/preview": csvPreview(),
      "POST /imports": () =>
        Response.json(
          { detail: "september.csv was already imported on Oct 3, 2026.", import_id: 3 },
          { status: 409 },
        ),
    });
    chooseFile(statementFile());

    fireEvent.click(await enabledButton("Import 84 transactions"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The file wasn't imported");
    expect(alert).toHaveTextContent("september.csv was already imported on Oct 3, 2026.");
    expect(alert).not.toHaveTextContent("[object");
    expect(screen.getByRole("button", { name: "Import 84 transactions" })).toBeEnabled();
  });

  it("explains a file the engine can't read", async () => {
    renderScreen({
      "GET /accounts": [CHECKING],
      "POST /imports/preview": () =>
        Response.json({ detail: "No transactions were found in the file." }, { status: 422 }),
    });

    chooseFile(statementFile());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Monelyth couldn't read this file");
    expect(alert).toHaveTextContent("No transactions were found in the file.");
  });

  it("warns early when an OFX statement's currency differs from the account's", async () => {
    renderScreen({
      "GET /accounts": [{ ...CHECKING, currency: "USD" }],
      "POST /imports/preview": {
        ...csvPreview({ format: "ofx", currency: "CAD", file_name: "export.qfx" }),
        csv: null,
      },
    });

    chooseFile(statementFile("export.qfx"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This statement is in CAD, but Main Checking uses USD.");
    expect(screen.getByText("OFX")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Date column" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import 84 transactions" })).toBeDisabled();
  });

  it("shows a retryable error when accounts can't be loaded", async () => {
    renderScreen({
      "GET /accounts": () => Response.json({ detail: "Database locked." }, { status: 503 }),
      "POST /imports/preview": csvPreview(),
    });

    chooseFile(statementFile());

    expect(await screen.findByText("Database locked.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  describe("drag and drop", () => {
    const files = (list: File[]) => ({ dataTransfer: { types: ["Files"], files: list } });

    it("highlights the drop zone while a file is dragged over the window", () => {
      renderScreen({ "GET /accounts": [CHECKING] });
      const zone = screen.getByRole("region", { name: "Choose a statement" });

      fireEvent.dragEnter(document.body, files([]));
      expect(zone).toHaveAttribute("data-dragging", "true");
      expect(screen.getByText("Drop the file to preview it")).toBeInTheDocument();

      fireEvent.dragLeave(document.body, files([]));
      expect(zone).toHaveAttribute("data-dragging", "false");
      expect(screen.getByText("Drag a statement here")).toBeInTheDocument();
    });

    it("ignores drags that carry no files", () => {
      renderScreen({ "GET /accounts": [CHECKING] });

      fireEvent.dragEnter(document.body, { dataTransfer: { types: ["text/plain"], files: [] } });

      expect(screen.getByRole("region", { name: "Choose a statement" })).toHaveAttribute(
        "data-dragging",
        "false",
      );
    });

    it("previews a dropped file", async () => {
      renderScreen({ "GET /accounts": [CHECKING], "POST /imports/preview": csvPreview() });

      fireEvent.dragEnter(document.body, files([]));
      fireEvent.drop(document.body, files([statementFile()]));

      expect(await screen.findByText("Blue Bottle")).toBeInTheDocument();
    });

    it("rejects several files at once", () => {
      renderScreen({ "GET /accounts": [CHECKING] });

      fireEvent.drop(document.body, files([statementFile("a.csv"), statementFile("b.csv")]));

      expect(screen.getByRole("alert")).toHaveTextContent(
        "That's 2 files. Import one statement at a time.",
      );
      expect(screen.getByRole("region", { name: "Choose a statement" })).toBeInTheDocument();
    });

    it("rejects a file that isn't a statement", () => {
      renderScreen({ "GET /accounts": [CHECKING] });

      chooseFile(statementFile("statement.pdf", "%PDF-1.7"));

      expect(screen.getByRole("alert")).toHaveTextContent('"statement.pdf" isn\'t a file');
    });
  });
});

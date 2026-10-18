import { CircleCheck, Upload } from "lucide-react";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";

import type { Account } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { paths } from "@/paths";
import type { ImportResult } from "@/screens/import/api";
import { importHeadline } from "@/screens/import/display";

interface ImportSummaryProps {
  result: ImportResult;
  account: Account;
  onImportAnother: () => void;
}

/** What an import added, and where to go next. */
export function ImportSummary({ result, account, onImportAnother }: ImportSummaryProps) {
  const navigate = useNavigate();
  const headingRef = useRef<HTMLHeadingElement>(null);

  // The button that started the import is gone; move focus to the outcome so keyboard and
  // screen reader users land on it.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-5 px-6 py-12 text-center">
        <div className="bg-success/10 text-success flex size-14 items-center justify-center rounded-full">
          <CircleCheck aria-hidden="true" className="size-7" />
        </div>
        <div className="flex flex-col gap-1.5">
          <h2 ref={headingRef} tabIndex={-1} className="text-xl font-semibold outline-none">
            {importHeadline(result.added, result.skipped_duplicates)}
          </h2>
          <p className="text-muted-foreground text-sm">
            From {result.file_name} into {account.name}.
          </p>
        </div>

        {result.warnings.length > 0 ? (
          <ul
            aria-label="Notes about this file"
            className="bg-muted/60 flex w-full max-w-xl flex-col gap-1.5 rounded-lg px-4 py-3 text-left"
          >
            {result.warnings.map((warning, index) => (
              <li key={`${String(index)}-${warning}`} className="text-muted-foreground text-sm">
                {warning}
              </li>
            ))}
          </ul>
        ) : null}

        <div className="flex flex-wrap justify-center gap-3">
          <Button
            onClick={() => {
              void navigate(paths.transactions);
            }}
          >
            View transactions
          </Button>
          <Button variant="outline" onClick={onImportAnother}>
            <Upload aria-hidden="true" />
            Import another file
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

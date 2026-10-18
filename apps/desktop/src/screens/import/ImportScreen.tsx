import { useIsMutating } from "@tanstack/react-query";
import { FileUp, ShieldCheck } from "lucide-react";
import { useState } from "react";

import type { Account } from "@/api/queries";
import { ScreenHeader } from "@/components/ScreenHeader";
import { cn } from "@/lib/utils";
import {
  commitMutationKey,
  type ImportResult,
  type StatementSelection,
} from "@/screens/import/api";
import { FileInputButton } from "@/screens/import/FileInputButton";
import { checkStatementFiles } from "@/screens/import/files";
import { ImportSummary } from "@/screens/import/ImportSummary";
import { Notice } from "@/screens/import/Notice";
import { ReviewImport } from "@/screens/import/ReviewImport";
import { useWindowFileDrop } from "@/screens/import/useWindowFileDrop";

type Stage =
  | { kind: "choose" }
  | { kind: "review"; selection: StatementSelection }
  | { kind: "done"; result: ImportResult; account: Account };

/** Choose a statement file, check what it holds, and import it into an account. */
export function ImportScreen() {
  const [stage, setStage] = useState<Stage>({ kind: "choose" });
  const [fileError, setFileError] = useState<string | null>(null);
  const importing = useIsMutating({ mutationKey: commitMutationKey }) > 0;

  function chooseFiles(files: File[]) {
    const check = checkStatementFiles(files);
    if (!check.ok) {
      // Keep whatever is on screen; a wrong drop shouldn't throw away a review in progress.
      setFileError(check.message);
      return;
    }
    setFileError(null);
    setStage({ kind: "review", selection: { id: crypto.randomUUID(), file: check.file } });
  }

  // Files can be dropped anywhere on the window, except while an import is being saved.
  const dragging = useWindowFileDrop(chooseFiles, !importing);

  return (
    <>
      <ScreenHeader
        title="Import a statement"
        description="Add transactions from a CSV or OFX file your bank lets you download."
      />

      {fileError === null ? null : (
        <Notice tone="error" title="That file can't be imported">
          {fileError}
        </Notice>
      )}

      {stage.kind === "choose" ? <DropZone dragging={dragging} onFiles={chooseFiles} /> : null}

      {stage.kind === "review" ? (
        <ReviewImport
          key={stage.selection.id}
          selection={stage.selection}
          onFiles={chooseFiles}
          onImported={(result, account) => {
            setStage({ kind: "done", result, account });
          }}
        />
      ) : null}

      {stage.kind === "done" ? (
        <ImportSummary
          result={stage.result}
          account={stage.account}
          onImportAnother={() => {
            setFileError(null);
            setStage({ kind: "choose" });
          }}
        />
      ) : null}

      {/* Past the first step the drop zone is gone, so show where a dragged file will land. */}
      {dragging && stage.kind !== "choose" ? <DropOverlay /> : null}
    </>
  );
}

interface DropZoneProps {
  dragging: boolean;
  onFiles: (files: File[]) => void;
}

function DropZone({ dragging, onFiles }: DropZoneProps) {
  return (
    <section
      aria-label="Choose a statement"
      data-dragging={dragging}
      className={cn(
        "flex flex-col items-center justify-center gap-5 rounded-xl border-2 border-dashed px-6 py-16 text-center transition-colors",
        dragging ? "border-primary bg-primary/5" : "border-border bg-card",
      )}
    >
      <div
        className={cn(
          "flex size-14 items-center justify-center rounded-full transition-colors",
          dragging ? "bg-primary text-primary-foreground" : "bg-primary/10 text-primary",
        )}
      >
        <FileUp aria-hidden="true" className="size-7" />
      </div>
      <div className="flex flex-col gap-1.5">
        <p className="text-lg font-semibold">
          {dragging ? "Drop the file to preview it" : "Drag a statement here"}
        </p>
        <p className="text-muted-foreground max-w-md text-sm">
          A CSV, OFX or QFX file from your bank's website. You'll see what's in it before anything
          is saved.
        </p>
      </div>
      <FileInputButton size="lg" onFiles={onFiles}>
        Choose file
      </FileInputButton>
      <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
        <ShieldCheck aria-hidden="true" className="size-3.5 shrink-0" />
        The file is read on this computer and never uploaded anywhere.
      </p>
    </section>
  );
}

function DropOverlay() {
  return (
    <div
      aria-hidden="true"
      className="bg-background/80 pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-8 backdrop-blur-sm"
    >
      <div className="border-primary bg-primary/5 flex size-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed">
        <FileUp aria-hidden="true" className="text-primary size-10" />
        <p className="text-lg font-semibold">Drop to preview this file instead</p>
      </div>
    </div>
  );
}

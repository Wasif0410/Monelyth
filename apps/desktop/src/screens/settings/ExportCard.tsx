import { open } from "@tauri-apps/plugin-dialog";
import { CircleCheck, FolderOutput } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/utils";
import { countOf } from "@/screens/accounts/text";
import { CopyButton } from "@/screens/settings/CopyButton";
import { useExportData } from "@/screens/settings/queries";
import { SettingsSection } from "@/screens/settings/SettingsSection";

/** Pick a folder, then write a copy of everything into a new folder inside it. */
export function ExportCard() {
  const exportData = useExportData();
  const [choosing, setChoosing] = useState(false);
  const busy = choosing || exportData.isPending;

  async function handleExport() {
    let folder: string | null;
    setChoosing(true);
    try {
      folder = await open({ directory: true, title: "Choose where to save your export" });
    } catch (error) {
      toast.error(`Couldn't open the folder picker. ${errorMessage(error)}`);
      return;
    } finally {
      setChoosing(false);
    }
    // null: the user closed the picker without choosing a folder.
    if (folder === null) return;
    exportData.mutate(folder);
  }

  return (
    <SettingsSection
      title="Export everything"
      description="A copy of the database plus a spreadsheet (CSV) of every transaction, saved in a new folder wherever you choose."
      icon={FolderOutput}
    >
      <div>
        <Button variant="outline" disabled={busy} onClick={() => void handleExport()}>
          {exportData.isPending ? "Exporting…" : "Export everything…"}
        </Button>
      </div>

      {exportData.isError ? (
        <p role="alert" className="text-destructive text-sm">
          {exportData.error.message}
        </p>
      ) : null}

      {exportData.isSuccess ? (
        <div
          role="status"
          className="border-success/30 bg-success/5 flex flex-col gap-2 rounded-lg border p-4"
        >
          <p className="flex items-center gap-2 text-sm font-medium">
            <CircleCheck aria-hidden="true" className="text-success size-4 shrink-0" />
            Exported {countOf(exportData.data.transaction_count, "transaction")} to:
          </p>
          <div className="flex items-center gap-2">
            <code className="bg-background min-w-0 flex-1 rounded-md border px-3 py-2 font-mono text-sm break-all">
              {exportData.data.path}
            </code>
            <CopyButton text={exportData.data.path} label="Copy export folder path" />
          </div>
        </div>
      ) : null}
    </SettingsSection>
  );
}

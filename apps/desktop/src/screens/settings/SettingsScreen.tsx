import { ShieldCheck } from "lucide-react";

import { ScreenHeader } from "@/components/ScreenHeader";
import { DataLocationCard } from "@/screens/settings/DataLocationCard";
import { DeleteEverythingCard } from "@/screens/settings/DeleteEverythingCard";
import { ExportCard } from "@/screens/settings/ExportCard";
import { useAppVersion, useSystemInfo } from "@/screens/settings/queries";

export function SettingsScreen() {
  return (
    <>
      <ScreenHeader
        title="Settings"
        description="Where your data lives, and how to take it with you or erase it."
      />
      <div className="flex max-w-3xl flex-col gap-6">
        <DataLocationCard />
        <ExportCard />
        <DeleteEverythingCard />
        <About />
      </div>
    </>
  );
}

/** Versions, for bug reports. Shares the system-info query with the data card. */
function About() {
  const appVersion = useAppVersion();
  const info = useSystemInfo();
  const versions = [
    // Outside the desktop shell (e.g. a plain browser) there is no app version to show.
    appVersion.isSuccess ? `Monelyth ${appVersion.data}` : null,
    info.isSuccess ? `engine ${info.data.engine_version}` : null,
  ].filter((part) => part !== null);

  return (
    <footer className="text-muted-foreground flex flex-wrap items-center justify-between gap-2 px-1 text-xs">
      <p className="flex items-center gap-1.5">
        <ShieldCheck aria-hidden="true" className="size-3.5 shrink-0" />
        Your data never leaves this computer.
      </p>
      {versions.length > 0 ? <p>{versions.join(" · ")}</p> : null}
    </footer>
  );
}

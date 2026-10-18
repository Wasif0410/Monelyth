import { HardDrive } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { QueryError } from "@/components/QueryError";
import { Skeleton } from "@/components/ui/skeleton";
import { paths } from "@/paths";
import { countOf } from "@/screens/accounts/text";
import { CopyButton } from "@/screens/settings/CopyButton";
import { formatBytes } from "@/screens/settings/format";
import { useSystemInfo } from "@/screens/settings/queries";
import { SettingsSection } from "@/screens/settings/SettingsSection";

/** Where the database is, how big it is and what it holds. */
export function DataLocationCard() {
  const info = useSystemInfo();

  return (
    <SettingsSection
      title="Your data"
      description="Everything Monelyth knows is in one database file on this computer."
      icon={HardDrive}
    >
      {info.isPending ? (
        <div role="status" aria-label="Loading data location" className="flex flex-col gap-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-12 w-2/3" />
        </div>
      ) : info.isError ? (
        <QueryError error={info.error} onRetry={() => void info.refetch()} />
      ) : (
        <dl className="grid grid-cols-3 gap-x-4 gap-y-5 text-sm">
          <div className="col-span-3">
            <dt className="text-muted-foreground text-xs">Data folder</dt>
            <dd className="mt-1.5 flex items-center gap-2">
              <code className="bg-muted min-w-0 flex-1 rounded-md px-3 py-2 font-mono text-sm break-all">
                {info.data.data_folder}
              </code>
              <CopyButton text={info.data.data_folder} label="Copy data folder path" />
            </dd>
          </div>
          <Stat label="Database size">{formatBytes(info.data.database_size_bytes)}</Stat>
          <Stat label="Accounts">
            <Link
              to={paths.accounts}
              className="text-primary font-medium underline-offset-4 hover:underline"
              aria-label={countOf(info.data.account_count, "account")}
            >
              {info.data.account_count.toLocaleString()}
            </Link>
          </Stat>
          <Stat label="Transactions">
            <Link
              to={paths.transactions}
              className="text-primary font-medium underline-offset-4 hover:underline"
              aria-label={countOf(info.data.transaction_count, "transaction")}
            >
              {info.data.transaction_count.toLocaleString()}
            </Link>
          </Stat>
        </dl>
      )}
    </SettingsSection>
  );
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="mt-1 text-base tabular-nums">{children}</dd>
    </div>
  );
}

import { ReceiptText, SearchX, Upload } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { paths } from "@/paths";

const SKELETON_ROWS = 10;

/** Placeholder while the toolbar's data (accounts, categories, months) loads. */
export function ToolbarSkeleton() {
  return (
    <div aria-hidden="true" className="flex flex-wrap items-center gap-2">
      <Skeleton className="h-9 w-64" />
      <Skeleton className="h-9 w-44" />
      <Skeleton className="h-9 w-56" />
      <Skeleton className="h-9 w-48" />
      <Skeleton className="h-9 w-36" />
    </div>
  );
}

/** Placeholder rows shaped like the table, while the first page loads. */
export function TableSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading transactions"
      className="bg-card min-h-0 flex-1 overflow-hidden rounded-lg border"
    >
      <div className="flex h-10 items-center gap-6 border-b px-4">
        <Skeleton className="h-3 w-12" />
        <Skeleton className="h-3 w-20" />
      </div>
      {Array.from({ length: SKELETON_ROWS }, (_, index) => (
        <div key={index} className="flex h-13 items-center gap-6 border-b px-4 last:border-b-0">
          <Skeleton className="h-4 w-20" />
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-4 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-7 w-36" />
          <Skeleton className="h-4 w-20" />
        </div>
      ))}
    </div>
  );
}

/** Nothing imported yet: point to the import screen. */
export function NoTransactionsYet() {
  return (
    <StateMessage
      icon={<ReceiptText aria-hidden="true" className="size-6" />}
      title="No transactions yet"
      description="Import a bank statement (CSV or OFX) and your transactions show up here, ready to sort into categories."
      action={
        <Button asChild>
          <Link to={paths.import}>
            <Upload aria-hidden="true" />
            Import a statement
          </Link>
        </Button>
      }
    />
  );
}

/** The filters exclude everything. */
export function NoMatches({ onClearFilters }: { onClearFilters?: () => void }) {
  return (
    <StateMessage
      icon={<SearchX aria-hidden="true" className="size-6" />}
      title="No matching transactions"
      description="Nothing matches these filters. Try a different month or search, or clear the filters."
      action={
        onClearFilters ? (
          <Button variant="outline" onClick={onClearFilters}>
            Clear filters
          </Button>
        ) : undefined
      }
    />
  );
}

interface StateMessageProps {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}

function StateMessage({ icon, title, description, action }: StateMessageProps) {
  return (
    <div className="bg-card flex min-h-0 flex-1 flex-col items-center justify-center gap-4 rounded-lg border px-6 py-12 text-center">
      <div className="bg-accent text-accent-foreground flex size-12 items-center justify-center rounded-full">
        {icon}
      </div>
      <div className="max-w-sm">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-muted-foreground mt-1 text-sm">{description}</p>
      </div>
      {action}
    </div>
  );
}

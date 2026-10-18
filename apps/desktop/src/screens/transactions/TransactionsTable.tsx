import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { LoaderCircle } from "lucide-react";
import { useEffect, useRef } from "react";

import type { Account } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate, formatMoney } from "@/lib/format";
import { cn, errorMessage } from "@/lib/utils";
import type { CategoryGroup } from "@/screens/transactions/categoryGroups";
import { CategorySelect } from "@/screens/transactions/CategorySelect";
import type { Transaction } from "@/screens/transactions/hooks";

/** Every row has the same height, so the virtualizer never needs to measure one. */
export const ROW_HEIGHT = 52;
/** Start loading the next page while this many loaded rows are still below the viewport. */
const LOAD_AHEAD_ROWS = 60;

interface TableMeta {
  accounts: ReadonlyMap<number, Account>;
  categoryGroups: readonly CategoryGroup[];
  onCategoryChange: (transaction: Transaction, categoryId: number) => void;
}

interface ColumnMeta {
  /** Fixed column width; the column without one takes the remaining space. */
  width?: string;
  /** Classes for the header and every cell, e.g. alignment. */
  className?: string;
  headerClassName?: string;
  cellClassName?: string;
}

// Type-only slots: they declare the types of `table.options.meta` and `columnDef.meta`.
const tableMeta = {} as TableMeta;
const columnMeta: ColumnMeta = {};
const features = tableFeatures({ tableMeta, columnMeta });
const column = createColumnHelper<typeof features, Transaction>();

function displayName(tx: Transaction): string {
  return tx.merchant ?? tx.description_raw;
}

function requireMeta(meta: TableMeta | undefined): TableMeta {
  if (meta === undefined) throw new Error("TransactionsTable renders its cells with table meta");
  return meta;
}

const columns = column.columns([
  column.accessor("posted_date", {
    header: "Date",
    meta: { width: "8rem", cellClassName: "text-muted-foreground" },
    cell: ({ getValue }) => formatDate(getValue()),
  }),
  column.accessor(displayName, {
    id: "merchant",
    header: "Merchant",
    cell: ({ row }) => {
      const tx = row.original;
      return (
        <div className="min-w-0">
          <p className="truncate font-medium" title={displayName(tx)}>
            {displayName(tx)}
          </p>
          {tx.merchant !== null ? (
            <p className="text-muted-foreground truncate text-xs" title={tx.description_raw}>
              {tx.description_raw}
            </p>
          ) : null}
        </div>
      );
    },
  }),
  column.accessor("account_id", {
    id: "account",
    header: "Account",
    meta: { width: "11rem", cellClassName: "text-muted-foreground" },
    cell: ({ getValue, table }) => {
      const name = requireMeta(table.options.meta).accounts.get(getValue())?.name;
      return (
        <span className="block truncate" title={name}>
          {name ?? "Unknown account"}
        </span>
      );
    },
  }),
  column.accessor("category_id", {
    id: "category",
    header: "Category",
    // The select's text sits inside its own padding; indent the header to line up with it.
    meta: { width: "14rem", headerClassName: "pl-7" },
    cell: ({ row, table }) => {
      const { categoryGroups, onCategoryChange } = requireMeta(table.options.meta);
      const tx = row.original;
      return (
        <CategorySelect
          transaction={tx}
          label={displayName(tx)}
          groups={categoryGroups}
          onChange={(categoryId) => {
            onCategoryChange(tx, categoryId);
          }}
        />
      );
    },
  }),
  column.accessor("amount_cents", {
    id: "amount",
    header: "Amount",
    meta: { width: "9rem", className: "text-right" },
    cell: ({ row, table }) => {
      const tx = row.original;
      const currency = requireMeta(table.options.meta).accounts.get(tx.account_id)?.currency;
      // Accounts are never deleted while they have transactions; this is only a safeguard.
      if (currency === undefined) return <span className="text-muted-foreground">—</span>;
      const moneyIn = tx.amount_cents > 0;
      return (
        <span className={cn("font-medium tabular-nums", moneyIn && "text-success")}>
          {moneyIn ? "+" : ""}
          {formatMoney(tx.amount_cents, currency)}
        </span>
      );
    },
  }),
]);

interface TransactionsTableProps {
  /** The rows loaded so far, newest first. Must keep its identity between renders. */
  transactions: readonly Transaction[];
  /** How many transactions match across all pages. */
  total: number;
  accounts: ReadonlyMap<number, Account>;
  categoryGroups: readonly CategoryGroup[];
  onCategoryChange: (transaction: Transaction, categoryId: number) => void;
  /** More transactions match than are loaded. */
  hasMore: boolean;
  /** Whether the next page may be requested now (nothing else is loading). */
  canLoadMore: boolean;
  /** Why the next page failed to load, or `null`; loading stops until the user retries. */
  loadMoreError: unknown;
  onLoadMore: () => void;
  /** The rows belong to the previous filters while the new ones load. */
  isStale: boolean;
}

/**
 * The transactions in a scrolling table that only renders the rows in view, so ten thousand
 * rows scroll as smoothly as ten. Scrolling near the end asks for the next page.
 */
export function TransactionsTable({
  transactions,
  total,
  accounts,
  categoryGroups,
  onCategoryChange,
  hasMore,
  canLoadMore,
  loadMoreError,
  onLoadMore,
  isStale,
}: TransactionsTableProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const table = useTable({
    features,
    columns,
    data: transactions,
    getRowId: (tx) => String(tx.id),
    meta: { accounts, categoryGroups, onCategoryChange },
  });
  const rows = table.getRowModel().rows;

  // The app doesn't use React Compiler, and this component reads the virtualizer afresh on
  // every render, so nothing can hold on to a stale result.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    getItemKey: (index) => rows[index]?.id ?? index,
    overscan: 12,
  });
  const virtualRows = virtualizer.getVirtualItems();
  const firstVirtual = virtualRows[0];
  const lastVirtual = virtualRows.at(-1);
  const paddingTop = firstVirtual?.start ?? 0;
  const paddingBottom = virtualizer.getTotalSize() - (lastVirtual?.end ?? 0);

  const lastRenderedIndex = lastVirtual?.index ?? -1;
  const loadMoreFailed = loadMoreError !== null;
  useEffect(() => {
    const nearTheEnd = lastRenderedIndex >= rows.length - LOAD_AHEAD_ROWS;
    if (nearTheEnd && canLoadMore && !loadMoreFailed) onLoadMore();
  }, [lastRenderedIndex, rows.length, canLoadMore, loadMoreFailed, onLoadMore]);

  const leafColumns = table.getAllLeafColumns();

  return (
    <div
      ref={scrollRef}
      role="region"
      aria-label="Transaction list"
      // Focusable so the list scrolls with the keyboard (arrows, Page Up/Down, Home/End).
      tabIndex={0}
      className="bg-card focus-visible:ring-ring/50 min-h-0 flex-1 overflow-auto rounded-lg border outline-none focus-visible:ring-[3px]"
    >
      <table
        aria-label="Transactions"
        aria-rowcount={total + 1}
        aria-busy={isStale}
        className={cn(
          "w-full min-w-[46rem] table-fixed text-sm transition-opacity",
          isStale && "opacity-60",
        )}
      >
        <colgroup>
          {leafColumns.map((col) => (
            <col key={col.id} style={{ width: col.columnDef.meta?.width }} />
          ))}
        </colgroup>
        <TableHeader className="bg-card sticky top-0 z-10 shadow-[inset_0_-1px_0_var(--color-border)] [&_tr]:border-b-0">
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id} aria-rowindex={1} className="hover:bg-transparent">
              {group.headers.map((header) => (
                <TableHead
                  key={header.id}
                  scope="col"
                  className={cn(
                    "text-muted-foreground px-4 text-xs font-medium tracking-wide uppercase",
                    header.column.columnDef.meta?.className,
                    header.column.columnDef.meta?.headerClassName,
                  )}
                >
                  {header.isPlaceholder ? null : <table.FlexRender header={header} />}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {paddingTop > 0 ? (
            <tr aria-hidden="true" style={{ height: paddingTop }}>
              <td colSpan={leafColumns.length} />
            </tr>
          ) : null}
          {virtualRows.map((item) => {
            const row = rows[item.index];
            if (row === undefined) return null;
            return (
              <TableRow key={row.id} aria-rowindex={item.index + 2} style={{ height: ROW_HEIGHT }}>
                {row.getAllCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className={cn(
                      "px-4 py-0",
                      cell.column.columnDef.meta?.className,
                      cell.column.columnDef.meta?.cellClassName,
                    )}
                  >
                    <table.FlexRender cell={cell} />
                  </TableCell>
                ))}
              </TableRow>
            );
          })}
          {paddingBottom > 0 ? (
            <tr aria-hidden="true" style={{ height: paddingBottom }}>
              <td colSpan={leafColumns.length} />
            </tr>
          ) : null}
          {hasMore || loadMoreFailed ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={leafColumns.length} className="h-14 text-center">
                <LoadMoreStatus error={loadMoreError} onRetry={onLoadMore} />
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </table>
    </div>
  );
}

function LoadMoreStatus({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  if (error !== null) {
    return (
      <span role="alert" className="text-muted-foreground inline-flex items-center gap-3">
        Couldn't load more transactions: {errorMessage(error)}
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </span>
    );
  }
  return (
    <span className="text-muted-foreground inline-flex items-center gap-2">
      <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
      Loading more…
    </span>
  );
}

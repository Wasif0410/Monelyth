import type { Schemas } from "@/api/client";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { formatAmount } from "@/screens/import/display";

interface PreviewTableProps {
  rows: readonly Schemas["PreviewRowOut"][];
  currency: string | null;
  caption: string;
}

/** The first transactions of a statement, as they will be stored. */
export function PreviewTable({ rows, currency, caption }: PreviewTableProps) {
  return (
    <Table>
      <caption className="sr-only">{caption}</caption>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="text-muted-foreground w-32 pl-5 text-xs uppercase tracking-wide">
            Date
          </TableHead>
          <TableHead className="text-muted-foreground text-xs uppercase tracking-wide">
            Merchant
          </TableHead>
          <TableHead className="text-muted-foreground pr-5 text-right text-xs uppercase tracking-wide">
            Amount
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          // Rows have no identity until they are stored, and their order never changes.
          <TableRow key={index}>
            <TableCell className="text-muted-foreground pl-5 tabular-nums">
              {formatDate(row.posted_date)}
            </TableCell>
            <TableCell className="max-w-0 w-full">
              <p className="truncate font-medium">{row.merchant}</p>
              {row.merchant !== row.description ? (
                <p className="text-muted-foreground truncate text-xs" title={row.description}>
                  {row.description}
                </p>
              ) : null}
            </TableCell>
            <TableCell
              className={cn(
                "pr-5 text-right font-medium tabular-nums",
                row.amount_cents > 0 ? "text-success" : "text-foreground",
              )}
            >
              {formatAmount(row.amount_cents, currency)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

import { useCallback, useMemo, type ReactNode } from "react";

import { useAccounts, useCategories } from "@/api/queries";
import { QueryError } from "@/components/QueryError";
import { ScreenHeader } from "@/components/ScreenHeader";
import { groupCategories } from "@/screens/transactions/categoryGroups";
import { hasActiveFilters, NO_FILTERS, toListQuery } from "@/screens/transactions/filters";
import {
  useSetCategory,
  useTransactionFilters,
  useTransactionPages,
  useTransactionRange,
  type Transaction,
} from "@/screens/transactions/hooks";
import { monthOf } from "@/screens/transactions/months";
import {
  NoMatches,
  NoTransactionsYet,
  TableSkeleton,
  ToolbarSkeleton,
} from "@/screens/transactions/TransactionStates";
import { TransactionsTable } from "@/screens/transactions/TransactionsTable";
import { TransactionsToolbar } from "@/screens/transactions/TransactionsToolbar";

export function TransactionsScreen() {
  const [filters, setFilters] = useTransactionFilters();
  const accounts = useAccounts();
  const categories = useCategories();
  const range = useTransactionRange();
  const pages = useTransactionPages(filters);
  const { mutate: setCategory } = useSetCategory();

  const accountsById = useMemo(
    () => new Map((accounts.data ?? []).map((account) => [account.id, account])),
    [accounts.data],
  );
  const categoryGroups = useMemo(() => groupCategories(categories.data ?? []), [categories.data]);
  const transactions = useMemo(() => uniqueById(pages.data?.pages ?? []), [pages.data]);

  const onCategoryChange = useCallback(
    (transaction: Transaction, categoryId: number) => {
      setCategory({ transaction, categoryId });
    },
    [setCategory],
  );
  const { fetchNextPage } = pages;
  const onLoadMore = useCallback(() => {
    void fetchNextPage();
  }, [fetchNextPage]);
  const clearFilters = useCallback(() => {
    setFilters(NO_FILTERS);
  }, [setFilters]);

  const setup = [accounts, categories, range];
  const setupError = setup.find((query) => query.isError);
  if (setupError) {
    return (
      <Layout>
        <QueryError
          error={setupError.error}
          onRetry={() => {
            for (const query of setup) if (query.isError) void query.refetch();
          }}
        />
      </Layout>
    );
  }
  if (!accounts.data || !categories.data || !range.data) {
    return (
      <Layout>
        <ToolbarSkeleton />
        <TableSkeleton />
      </Layout>
    );
  }

  const { first_date: firstDate, last_date: lastDate } = range.data;
  if (firstDate === null || lastDate === null) {
    return (
      <Layout>
        <NoTransactionsYet />
      </Layout>
    );
  }

  const total = pages.data?.pages[0]?.total;
  let content: ReactNode;
  if (pages.isError && !pages.isFetchNextPageError) {
    content = <QueryError error={pages.error} onRetry={() => void pages.refetch()} />;
  } else if (!pages.data || total === undefined) {
    content = <TableSkeleton />;
  } else if (total === 0) {
    content = (
      <NoMatches {...(hasActiveFilters(filters) ? { onClearFilters: clearFilters } : {})} />
    );
  } else {
    content = (
      <TransactionsTable
        // A new set of filters starts again at the top of the list.
        key={JSON.stringify(toListQuery(filters))}
        transactions={transactions}
        total={total}
        accounts={accountsById}
        categoryGroups={categoryGroups}
        onCategoryChange={onCategoryChange}
        hasMore={pages.hasNextPage}
        canLoadMore={pages.hasNextPage && !pages.isFetching && !pages.isPlaceholderData}
        loadMoreError={pages.isFetchNextPageError ? pages.error : null}
        onLoadMore={onLoadMore}
        isStale={pages.isPlaceholderData}
      />
    );
  }

  return (
    <Layout>
      <TransactionsToolbar
        filters={filters}
        onChange={setFilters}
        accounts={accounts.data}
        categoryGroups={categoryGroups}
        months={{ first: monthOf(firstDate), last: monthOf(lastDate) }}
        total={total}
      />
      {content}
    </Layout>
  );
}

/**
 * Fills the main area's height (the layout pads it by 2rem top and bottom), so the table, not
 * the page, scrolls and its header stays in view.
 */
function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-[calc(100dvh-4rem)] min-h-[30rem] flex-col gap-5">
      <ScreenHeader title="Transactions" description="Everything you've imported, newest first." />
      {children}
    </div>
  );
}

/**
 * The loaded pages as one list. Offset paging can repeat a row when transactions are added
 * between two page loads; React needs each row once.
 */
function uniqueById(pages: readonly { items: readonly Transaction[] }[]): Transaction[] {
  const seen = new Set<number>();
  const rows: Transaction[] = [];
  for (const page of pages) {
    for (const tx of page.items) {
      if (seen.has(tx.id)) continue;
      seen.add(tx.id);
      rows.push(tx);
    }
  }
  return rows;
}

import { Navigate } from "react-router";

import { useAccounts } from "@/api/queries";
import { QueryError } from "@/components/QueryError";
import { paths } from "@/paths";

/** Sends a first-time user (no accounts yet) to onboarding, everyone else to their data. */
export function HomeRedirect() {
  const accounts = useAccounts();

  if (accounts.isPending) return null;
  if (accounts.isError) {
    return (
      <div className="mx-auto max-w-md p-8">
        <QueryError error={accounts.error} onRetry={() => void accounts.refetch()} />
      </div>
    );
  }
  return <Navigate to={accounts.data.length === 0 ? paths.welcome : paths.transactions} replace />;
}

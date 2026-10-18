import { createHashRouter, Navigate } from "react-router";

import { AppLayout } from "@/components/AppLayout";
import { HomeRedirect } from "@/components/HomeRedirect";
import { RouteError } from "@/components/RouteError";
import { paths } from "@/paths";
import { AccountsScreen } from "@/screens/accounts/AccountsScreen";
import { ImportScreen } from "@/screens/import/ImportScreen";
import { OnboardingScreen } from "@/screens/onboarding/OnboardingScreen";
import { SettingsScreen } from "@/screens/settings/SettingsScreen";
import { TransactionsScreen } from "@/screens/transactions/TransactionsScreen";

/**
 * Hash routing (`#/transactions`) because the app is served from a fixed local origin with no
 * server to rewrite deep links; a reload keeps the current screen.
 */
export function createAppRouter() {
  return createHashRouter([
    {
      errorElement: <RouteError />,
      children: [
        { path: paths.home, element: <HomeRedirect /> },
        // Onboarding is full-screen, outside the sidebar layout.
        { path: paths.welcome, element: <OnboardingScreen /> },
        {
          element: <AppLayout />,
          children: [
            { path: paths.transactions, element: <TransactionsScreen /> },
            { path: paths.import, element: <ImportScreen /> },
            { path: paths.accounts, element: <AccountsScreen /> },
            { path: paths.settings, element: <SettingsScreen /> },
          ],
        },
        { path: "*", element: <Navigate to={paths.home} replace /> },
      ],
    },
  ]);
}

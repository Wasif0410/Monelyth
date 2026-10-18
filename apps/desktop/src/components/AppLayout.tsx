import {
  ClipboardCheck,
  Landmark,
  List,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { NavLink, Outlet } from "react-router";

import { Logo } from "@/components/Logo";
import { cn } from "@/lib/utils";
import { paths } from "@/paths";
import { CategorizationIndicator } from "@/screens/review/CategorizationIndicator";
import { useReviewSummary } from "@/screens/review/queries";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: paths.transactions, label: "Transactions", icon: List },
  { to: paths.review, label: "Review", icon: ClipboardCheck },
  { to: paths.import, label: "Import", icon: Upload },
  { to: paths.accounts, label: "Accounts", icon: Landmark },
  { to: paths.rules, label: "Rules", icon: SlidersHorizontal },
  { to: paths.settings, label: "Settings", icon: Settings },
];

const countFormat = new Intl.NumberFormat();

/** Sidebar navigation around the current screen. */
export function AppLayout() {
  const waiting = useReviewSummary().data?.waiting ?? 0;

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="bg-sidebar flex w-56 shrink-0 flex-col border-r">
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-6">
          <Logo className="size-8 text-sm" />
          <span className="text-lg font-semibold tracking-tight">Monelyth</span>
        </div>

        <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 px-3">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => {
            const count = to === paths.review ? waiting : 0;
            return (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                  )
                }
              >
                <Icon aria-hidden="true" className="size-4" />
                {label}
                {count > 0 ? (
                  <>
                    <span className="sr-only">, {countFormat.format(count)} waiting</span>
                    <span
                      aria-hidden="true"
                      className="bg-primary text-primary-foreground ml-auto min-w-5 rounded-full px-1.5 text-center text-xs leading-5 font-semibold tabular-nums"
                    >
                      {countFormat.format(count)}
                    </span>
                  </>
                ) : null}
              </NavLink>
            );
          })}
        </nav>

        <CategorizationIndicator />
        <p className="text-muted-foreground flex items-center gap-1.5 px-5 py-4 text-xs">
          <ShieldCheck aria-hidden="true" className="size-3.5 shrink-0" />
          Stays on this computer
        </p>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

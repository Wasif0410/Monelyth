import { Landmark, List, Settings, ShieldCheck, Upload, type LucideIcon } from "lucide-react";
import { NavLink, Outlet } from "react-router";

import { Logo } from "@/components/Logo";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: "/transactions", label: "Transactions", icon: List },
  { to: "/import", label: "Import", icon: Upload },
  { to: "/accounts", label: "Accounts", icon: Landmark },
  { to: "/settings", label: "Settings", icon: Settings },
];

/** Sidebar navigation around the current screen. */
export function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="bg-sidebar flex w-56 shrink-0 flex-col border-r">
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-6">
          <Logo className="size-8 text-sm" />
          <span className="text-lg font-semibold tracking-tight">Monelyth</span>
        </div>

        <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 px-3">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
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
            </NavLink>
          ))}
        </nav>

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

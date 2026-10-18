import type { ReactNode } from "react";

interface ScreenHeaderProps {
  title: string;
  description?: string;
  /** Buttons shown on the right, e.g. the screen's main action. */
  actions?: ReactNode;
}

/** The title row at the top of every screen inside the app layout. */
export function ScreenHeader({ title, description, actions }: ScreenHeaderProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="text-muted-foreground mt-1 text-sm">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}

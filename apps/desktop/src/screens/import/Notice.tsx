import { CircleAlert, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Tone = "error" | "warning" | "info";

const TONES: Record<Tone, { icon: LucideIcon; box: string; iconClass: string }> = {
  error: {
    icon: CircleAlert,
    box: "border-destructive/30 bg-destructive/5",
    iconClass: "text-destructive",
  },
  warning: {
    icon: TriangleAlert,
    box: "border-warning/40 bg-warning/10",
    iconClass: "text-warning",
  },
  info: { icon: Info, box: "bg-muted/60", iconClass: "text-muted-foreground" },
};

interface NoticeProps {
  tone: Tone;
  title: string;
  children?: ReactNode;
  /** Buttons shown under the text. */
  actions?: ReactNode;
  className?: string;
}

/**
 * A message inside the import flow. Errors and warnings are announced when they appear, since
 * they change what the user can do next.
 */
export function Notice({ tone, title, children, actions, className }: NoticeProps) {
  const { icon: Icon, box, iconClass } = TONES[tone];
  return (
    <div
      role={tone === "info" ? undefined : "alert"}
      className={cn("flex items-start gap-3 rounded-lg border p-4", box, className)}
    >
      <Icon aria-hidden="true" className={cn("mt-0.5 size-5 shrink-0", iconClass)} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        {children ? (
          <div className="text-muted-foreground mt-0.5 text-sm break-words">{children}</div>
        ) : null}
        {actions ? <div className="mt-3 flex flex-wrap gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

import type { LucideIcon } from "lucide-react";
import { useId, type ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface SettingsSectionProps {
  title: string;
  description: ReactNode;
  icon: LucideIcon;
  tone?: "default" | "danger";
  children: ReactNode;
}

/** One titled card on the Settings screen, exposed as a labelled region. */
export function SettingsSection({
  title,
  description,
  icon: Icon,
  tone = "default",
  children,
}: SettingsSectionProps) {
  const titleId = useId();
  const danger = tone === "danger";

  return (
    <section aria-labelledby={titleId}>
      <Card className={cn(danger && "border-destructive/40")}>
        <CardContent className="flex flex-col gap-5">
          <div className="flex items-start gap-3">
            <span
              className={cn(
                "flex size-9 shrink-0 items-center justify-center rounded-lg",
                danger ? "bg-destructive/10 text-destructive" : "bg-accent text-accent-foreground",
              )}
            >
              <Icon aria-hidden="true" className="size-[1.125rem]" />
            </span>
            <div className="min-w-0">
              <h2 id={titleId} className="font-medium">
                {title}
              </h2>
              <p className="text-muted-foreground mt-0.5 text-sm">{description}</p>
            </div>
          </div>
          {children}
        </CardContent>
      </Card>
    </section>
  );
}

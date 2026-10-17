import { CircleAlert, CircleCheck, CircleX, LoaderCircle, type LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { EngineStatus } from "@/engine/status";
import type { HealthState } from "@/engine/useEngineHealth";
import { cn } from "@/lib/utils";

interface EngineStatusCardProps {
  status: EngineStatus;
  health: HealthState;
}

interface View {
  icon: LucideIcon;
  tone: "neutral" | "success" | "warning" | "danger";
  title: string;
  detail: string;
}

const TONE_CLASSES: Record<View["tone"], string> = {
  neutral: "text-muted-foreground",
  success: "text-success",
  warning: "text-warning",
  danger: "text-destructive",
};

export function EngineStatusCard({ status, health }: EngineStatusCardProps) {
  const view = describe(status, health);
  const Icon = view.icon;
  const busy = view.icon === LoaderCircle;

  return (
    <Card className="w-full">
      <CardContent className="flex items-start gap-3">
        <Icon
          aria-hidden="true"
          className={cn("mt-0.5 size-5 shrink-0", TONE_CLASSES[view.tone], busy && "animate-spin")}
        />
        <div role="status" aria-live="polite" aria-busy={busy} className="min-w-0 text-left">
          <p className="text-sm font-medium">{view.title}</p>
          <p className="text-muted-foreground mt-0.5 text-sm break-words">{view.detail}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function describe(status: EngineStatus, health: HealthState): View {
  switch (status.state) {
    case "starting":
      return {
        icon: LoaderCircle,
        tone: "neutral",
        title: "Starting the engine…",
        detail: "This usually takes a few seconds.",
      };
    case "failed":
      return {
        icon: CircleX,
        tone: "danger",
        title: "The engine couldn't start",
        detail: `${status.message} Restart Monelyth to try again.`,
      };
    case "ready":
      return describeHealth(health, status.version);
  }
}

function describeHealth(health: HealthState, version: string): View {
  switch (health.kind) {
    case "idle":
    case "checking":
      return {
        icon: LoaderCircle,
        tone: "neutral",
        title: "Connecting to the engine…",
        detail: `Engine ${version} has started.`,
      };
    case "ok":
      return {
        icon: CircleCheck,
        tone: "success",
        title: "Engine connected",
        detail: `Version ${health.version}, running only on this computer.`,
      };
    case "error":
      return {
        icon: CircleAlert,
        tone: "warning",
        title: "The engine isn't responding",
        detail: health.message,
      };
  }
}

import { ShieldCheck } from "lucide-react";

import { EngineStatusCard } from "@/components/EngineStatusCard";
import { Logo } from "@/components/Logo";
import type { EngineStatus } from "@/engine/status";
import type { HealthState } from "@/engine/useEngineHealth";

interface StartupScreenProps {
  status: EngineStatus;
  health: HealthState;
}

/** Shown until the engine is connected, or when it fails to start. */
export function StartupScreen({ status, health }: StartupScreenProps) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-6 py-12">
      <div className="flex w-full max-w-sm flex-col items-center gap-8 text-center">
        <div className="flex flex-col items-center gap-4">
          <Logo className="size-14 text-2xl" />
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Monelyth</h1>
            <p className="text-muted-foreground mt-2">Your money, understood. Privately.</p>
          </div>
        </div>

        <EngineStatusCard status={status} health={health} />

        <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <ShieldCheck aria-hidden="true" className="size-3.5" />
          Your data never leaves this computer.
        </p>
      </div>
    </main>
  );
}

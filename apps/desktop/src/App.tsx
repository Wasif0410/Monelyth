import { ShieldCheck } from "lucide-react";

import { EngineStatusCard } from "@/components/EngineStatusCard";
import { useEngineHealth } from "@/engine/useEngineHealth";
import { useEngineStatus } from "@/engine/useEngineStatus";

export function App() {
  const status = useEngineStatus();
  const health = useEngineHealth(status);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-6 py-12">
      <div className="flex w-full max-w-sm flex-col items-center gap-8 text-center">
        <div className="flex flex-col items-center gap-4">
          <div
            aria-hidden="true"
            className="bg-primary text-primary-foreground flex size-14 items-center justify-center rounded-2xl text-2xl font-semibold shadow-sm"
          >
            M
          </div>
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

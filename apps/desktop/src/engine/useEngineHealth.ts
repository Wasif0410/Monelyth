import { useEffect, useState } from "react";

import { fetchHealth } from "@/engine/client";
import type { EngineStatus } from "@/engine/status";
import { errorMessage } from "@/lib/utils";

export type HealthState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "ok"; version: string }
  | { kind: "error"; message: string };

type HealthResult = Extract<HealthState, { kind: "ok" | "error" }>;

/** Once the engine reports ready, confirm the UI can actually reach it over HTTP. */
export function useEngineHealth(status: EngineStatus): HealthState {
  const port = status.state === "ready" ? status.port : undefined;
  const token = status.state === "ready" ? status.token : undefined;
  const key = port === undefined || token === undefined ? undefined : `${String(port)}:${token}`;

  // Each result is stored with the connection it belongs to, so a result from a previous
  // engine instance is never shown for the current one.
  const [result, setResult] = useState<{ key: string; value: HealthResult }>();

  useEffect(() => {
    if (key === undefined || port === undefined || token === undefined) return;

    const controller = new AbortController();
    fetchHealth({ port, token }, controller.signal).then(
      (health) => {
        setResult({ key, value: { kind: "ok", version: health.version } });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setResult({ key, value: { kind: "error", message: errorMessage(error) } });
      },
    );
    return () => {
      controller.abort();
    };
  }, [key, port, token]);

  if (key === undefined) return { kind: "idle" };
  if (result?.key !== key) return { kind: "checking" };
  return result.value;
}

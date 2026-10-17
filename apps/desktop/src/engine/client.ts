import type { EngineConnection } from "@/engine/status";

/** How long a request may take before the UI treats the engine as unresponsive. */
export const REQUEST_TIMEOUT_MS = 5_000;

export interface Health {
  status: "ok";
  version: string;
}

export class EngineRequestError extends Error {
  readonly status: number | undefined;

  constructor(message: string, options: { status?: number; cause?: unknown } = {}) {
    super(message, { cause: options.cause });
    this.name = "EngineRequestError";
    this.status = options.status;
  }
}

export function engineUrl(connection: EngineConnection, path: `/${string}`): string {
  return `http://127.0.0.1:${String(connection.port)}${path}`;
}

/**
 * Call the engine's `/health` route.
 *
 * Rejects with the caller's abort reason if `signal` is aborted, and with `EngineRequestError`
 * for every other failure (unreachable, timeout, error status, unexpected body).
 */
export async function fetchHealth(
  connection: EngineConnection,
  signal?: AbortSignal,
): Promise<Health> {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  let response: Response;
  try {
    response = await fetch(engineUrl(connection, "/health"), {
      headers: { Authorization: `Bearer ${connection.token}` },
      signal: combined,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    const reason = timeout.aborted ? "did not respond in time" : "could not be reached";
    throw new EngineRequestError(`The engine ${reason}.`, { cause: error });
  }

  if (!response.ok) {
    throw new EngineRequestError(`The engine responded with HTTP ${String(response.status)}.`, {
      status: response.status,
    });
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    throw new EngineRequestError("The engine sent a response that is not JSON.", { cause: error });
  }
  if (!isHealth(body)) {
    throw new EngineRequestError("The engine sent an unexpected health response.");
  }
  return body;
}

function isHealth(value: unknown): value is Health {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return record.status === "ok" && typeof record.version === "string";
}

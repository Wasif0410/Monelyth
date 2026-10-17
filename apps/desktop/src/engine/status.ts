/**
 * Engine status as reported by the Rust shell. Must match `EngineSnapshot` in
 * src-tauri/src/engine.rs.
 */

/** Tauri event the shell emits whenever the engine status changes. */
export const ENGINE_STATUS_EVENT = "engine-status";

/** Tauri command that returns the current status. */
export const GET_ENGINE_STATUS_COMMAND = "get_engine_status";

/** Where the engine is listening and the secret every request must carry. */
export interface EngineConnection {
  port: number;
  token: string;
}

export type EngineStatus =
  | { state: "starting" }
  | ({ state: "ready"; version: string } & EngineConnection)
  | { state: "failed"; message: string };

/**
 * A status plus its sequence number. The shell increments `seq` on every change, so the UI can
 * tell which of two snapshots is newer even if they arrive out of order.
 */
export type EngineSnapshot = EngineStatus & { seq: number };

export class InvalidEngineStatusError extends Error {
  constructor(value: unknown) {
    super(`Received an invalid engine status: ${JSON.stringify(value)}`);
    this.name = "InvalidEngineStatusError";
  }
}

export function parseEngineSnapshot(value: unknown): EngineSnapshot {
  if (!isRecord(value) || !isNonNegativeInteger(value.seq)) {
    throw new InvalidEngineStatusError(value);
  }
  const { seq } = value;

  switch (value.state) {
    case "starting":
      return { seq, state: "starting" };
    case "ready":
      if (isPort(value.port) && isNonEmptyString(value.token) && isNonEmptyString(value.version)) {
        return {
          seq,
          state: "ready",
          port: value.port,
          token: value.token,
          version: value.version,
        };
      }
      break;
    case "failed":
      if (isNonEmptyString(value.message)) {
        return { seq, state: "failed", message: value.message };
      }
      break;
  }
  throw new InvalidEngineStatusError(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isPort(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 65535;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

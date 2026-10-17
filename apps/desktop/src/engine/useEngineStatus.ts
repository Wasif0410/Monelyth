import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useState } from "react";

import {
  ENGINE_STATUS_EVENT,
  GET_ENGINE_STATUS_COMMAND,
  parseEngineSnapshot,
  type EngineSnapshot,
  type EngineStatus,
} from "@/engine/status";
import { errorMessage } from "@/lib/utils";

const INITIAL: EngineSnapshot = { seq: -1, state: "starting" };

/** Live engine status from the Rust shell. */
export function useEngineStatus(): EngineStatus {
  const [snapshot, setSnapshot] = useState<EngineSnapshot>(INITIAL);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;

    const fail = (message: string) => {
      setSnapshot((current) => ({ seq: current.seq, state: "failed", message }));
    };

    const apply = (value: unknown) => {
      if (disposed) return;
      let next: EngineSnapshot;
      try {
        next = parseEngineSnapshot(value);
      } catch (error) {
        fail(errorMessage(error));
        return;
      }
      // Keep whichever snapshot is newest; the event and the command can race.
      setSnapshot((current) => (next.seq > current.seq ? next : current));
    };

    const subscribe = async () => {
      try {
        // Subscribe before asking for the current status, so a change that happens in
        // between is delivered as an event rather than missed.
        const stop = await listen<unknown>(ENGINE_STATUS_EVENT, (event) => {
          apply(event.payload);
        });
        if (disposed) {
          stop();
          return;
        }
        unlisten = stop;
        apply(await invoke<unknown>(GET_ENGINE_STATUS_COMMAND));
      } catch (error) {
        if (!disposed) fail(`Could not reach the app shell: ${errorMessage(error)}`);
      }
    };

    void subscribe();
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  return toStatus(snapshot);
}

function toStatus(snapshot: EngineSnapshot): EngineStatus {
  switch (snapshot.state) {
    case "starting":
      return { state: "starting" };
    case "ready":
      return {
        state: "ready",
        port: snapshot.port,
        token: snapshot.token,
        version: snapshot.version,
      };
    case "failed":
      return { state: "failed", message: snapshot.message };
  }
}

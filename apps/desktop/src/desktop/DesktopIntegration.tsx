import { isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef } from "react";

import { notifyIfAway } from "@/desktop/notify";
import { paths } from "@/paths";
import { useCategorizationStatus } from "@/screens/review/queries";

/** Must match `NAVIGATE_EVENT` in src-tauri/src/desktop.rs. */
const NAVIGATE_EVENT = "navigate";

const NAVIGABLE: ReadonlySet<string> = new Set(Object.values(paths));

interface DesktopIntegrationProps {
  /** Opens a route, e.g. the router's `navigate`. */
  navigate: (path: string) => void;
}

/**
 * Connects the desktop shell to the UI: the tray menu can open a screen, and a background
 * categorization run that finishes while the user is elsewhere ends with a notification.
 * Renders nothing; mount once inside the API providers.
 */
export function DesktopIntegration({ navigate }: DesktopIntegrationProps) {
  useTrayNavigation(navigate);
  useRunFinishedNotification();
  return null;
}

function useTrayNavigation(navigate: (path: string) => void) {
  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void listen<unknown>(NAVIGATE_EVENT, ({ payload }) => {
      // Only known screens: the event is ours, but the router should never get arbitrary input.
      if (typeof payload === "string" && NAVIGABLE.has(payload)) navigate(payload);
    }).then((stop) => {
      if (disposed) stop();
      else unlisten = stop;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [navigate]);
}

function useRunFinishedNotification() {
  const { data: status } = useCategorizationStatus();
  const seenRuns = useRef<number | undefined>(undefined);
  const runsFinished = status?.runs_finished;
  const processed = status?.processed ?? 0;

  useEffect(() => {
    if (runsFinished === undefined) return;
    const previous = seenRuns.current;
    seenRuns.current = runsFinished;
    if (previous === undefined || runsFinished === previous || processed === 0) return;
    void notifyIfAway(
      "Categorizing finished",
      processed === 1
        ? "1 transaction was categorized. Open Monelyth to see it."
        : `${processed.toLocaleString()} transactions were categorized. Open Monelyth to review them.`,
    );
  }, [runsFinished, processed]);
}

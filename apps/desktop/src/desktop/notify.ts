import { isTauri } from "@tauri-apps/api/core";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";

import { readPreferences } from "@/desktop/preferences";

/** Whether the user is looking at Monelyth right now (window focused and not hidden). */
export function isAppInFront(): boolean {
  return document.visibilityState === "visible" && document.hasFocus();
}

/**
 * Show a Windows notification, but only when it helps: the user turned notifications on and
 * isn't already looking at Monelyth. Never throws; a notification is a courtesy.
 */
export async function notifyIfAway(title: string, body: string): Promise<void> {
  if (!isTauri() || isAppInFront()) return;
  try {
    const preferences = await readPreferences();
    if (!preferences.notifications) return;
    let granted = await isPermissionGranted();
    if (!granted) granted = (await requestPermission()) === "granted";
    if (granted) sendNotification({ title, body });
  } catch {
    // Notifications are optional; failing to show one must never disturb the app.
  }
}

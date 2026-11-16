/**
 * The user's desktop preferences, kept in Tauri's `preferences.json` store so the Rust shell
 * can read them too (src-tauri/src/desktop.rs). Start-at-sign-in is not stored here: Windows
 * itself records it, through the autostart plugin.
 */
import { isTauri } from "@tauri-apps/api/core";
import { disable, enable, isEnabled } from "@tauri-apps/plugin-autostart";
import { load, type Store } from "@tauri-apps/plugin-store";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

/** Must match `PREFERENCES_STORE` in src-tauri/src/desktop.rs. */
export const PREFERENCES_STORE = "preferences.json";

export interface DesktopPreferences {
  /** Closing the window hides it to the tray instead of quitting. Read by the Rust shell. */
  closeToTray: boolean;
  /** Show Windows notifications when something finishes while Monelyth isn't in front. */
  notifications: boolean;
  /** Open Monelyth (quietly, in the tray) when the user signs in to Windows. */
  startAtSignIn: boolean;
}

type StoredPreference = Exclude<keyof DesktopPreferences, "startAtSignIn">;

export const DEFAULT_PREFERENCES: DesktopPreferences = {
  closeToTray: false,
  notifications: true,
  startAtSignIn: false,
};

export const desktopKeys = {
  preferences: ["desktop", "preferences"] as const,
};

let storePromise: Promise<Store> | undefined;

function preferencesStore(): Promise<Store> {
  storePromise ??= load(PREFERENCES_STORE, {
    defaults: { closeToTray: DEFAULT_PREFERENCES.closeToTray, notifications: true },
    autoSave: true,
  });
  return storePromise;
}

export async function readPreferences(): Promise<DesktopPreferences> {
  // Outside the desktop shell (tests, a plain browser) there is nothing to read.
  if (!isTauri()) return DEFAULT_PREFERENCES;
  const store = await preferencesStore();
  const [closeToTray, notifications, startAtSignIn] = await Promise.all([
    store.get<boolean>("closeToTray"),
    store.get<boolean>("notifications"),
    isEnabled(),
  ]);
  return {
    closeToTray: closeToTray ?? DEFAULT_PREFERENCES.closeToTray,
    notifications: notifications ?? DEFAULT_PREFERENCES.notifications,
    startAtSignIn,
  };
}

async function writePreference(key: keyof DesktopPreferences, value: boolean) {
  if (key === "startAtSignIn") {
    await (value ? enable() : disable());
    return;
  }
  const store = await preferencesStore();
  await store.set(key satisfies StoredPreference, value);
  // autoSave debounces; save now so the Rust shell sees the choice if the window closes next.
  await store.save();
}

export function useDesktopPreferences() {
  return useQuery({ queryKey: desktopKeys.preferences, queryFn: readPreferences });
}

export function useSetDesktopPreference() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value }: { key: keyof DesktopPreferences; value: boolean }) =>
      writePreference(key, value),
    onMutate: async ({ key, value }) => {
      await queryClient.cancelQueries({ queryKey: desktopKeys.preferences });
      const previous = queryClient.getQueryData<DesktopPreferences>(desktopKeys.preferences);
      if (previous) {
        queryClient.setQueryData<DesktopPreferences>(desktopKeys.preferences, {
          ...previous,
          [key]: value,
        });
      }
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(desktopKeys.preferences, context.previous);
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: desktopKeys.preferences }),
  });
}

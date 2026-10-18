/** Queries and mutations only the Settings screen uses. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { getVersion } from "@tauri-apps/api/app";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";

export type SystemInfo = Schemas["SystemInfoOut"];
export type ExportResult = Schemas["ExportOut"];

export const settingsKeys = {
  systemInfo: ["system-info"] as const,
  appVersion: ["app-version"] as const,
};

/** Where the data lives, how big it is, and how much of it there is. */
export function useSystemInfo() {
  const api = useApi();
  return useQuery({
    queryKey: settingsKeys.systemInfo,
    queryFn: ({ signal }) => unwrap(api.GET("/system/info", { signal })),
  });
}

/** The desktop app's version, from the Tauri shell. */
export function useAppVersion() {
  return useQuery({
    queryKey: settingsKeys.appVersion,
    queryFn: getVersion,
    staleTime: Infinity,
  });
}

/** Write everything to a new folder inside `folder` (a full path). */
export function useExportData() {
  const api = useApi();
  return useMutation({
    mutationFn: (folder: string) => unwrap(api.POST("/data/export", { body: { folder } })),
  });
}

/**
 * Erase all of the user's data. The caller must then clear the whole query cache, since every
 * cached answer from the engine is now wrong.
 */
export function useEraseData() {
  const api = useApi();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/data/erase", { body: { confirm: "DELETE" } })),
  });
}

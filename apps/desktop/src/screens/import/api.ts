/** The import screen's engine calls: preview a statement file, then import it. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { queryKeys } from "@/api/queries";
import type { CsvLayout } from "@/screens/import/layout";

export type ImportPreview = Schemas["ImportPreviewOut"];
export type ImportResult = Schemas["ImportResultOut"];

/** A file the user chose. `id` tells two choices of the same file apart. */
export interface StatementSelection {
  id: string;
  file: File;
}

/** Lets the screen tell when an import is running, to ignore files dropped meanwhile. */
export const commitMutationKey = ["imports", "commit"] as const;

/**
 * Preview `selection`, letting the engine detect a CSV layout, or reading every row with
 * `layout` when given. While a new layout is previewed, the previous result stays visible
 * (`isPlaceholderData`), so the table doesn't flash empty on each change.
 */
export function useImportPreview(
  selection: StatementSelection,
  layout: CsvLayout | null,
  options: { enabled?: boolean } = {},
) {
  const api = useApi();
  return useQuery({
    queryKey: ["imports", "preview", selection.id, layout] as const,
    queryFn: ({ signal }) =>
      unwrap(
        api.POST("/imports/preview", {
          body: {
            file: filePart(selection.file),
            ...(layout === null ? {} : { layout: JSON.stringify(layout) }),
          },
          bodySerializer: toFormData,
          signal,
        }),
      ),
    enabled: options.enabled ?? true,
    placeholderData: keepPreviousData,
    // The file can't change under us, and a failed read fails the same way every time.
    staleTime: Infinity,
    retry: false,
  });
}

interface CommitInput {
  file: File;
  accountId: number;
  /** Required for CSV files, refused for OFX. */
  layout: CsvLayout | null;
}

export function useCommitImport() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: commitMutationKey,
    mutationFn: ({ file, accountId, layout }: CommitInput) =>
      unwrap(
        api.POST("/imports", {
          body: {
            file: filePart(file),
            account_id: accountId,
            ...(layout === null ? {} : { layout: JSON.stringify(layout) }),
          },
          bodySerializer: toFormData,
        }),
      ),
    onSuccess: () => {
      // Not awaited: the summary shows at once while other views refresh in the background.
      void queryClient.invalidateQueries({ queryKey: queryKeys.transactions });
      void queryClient.invalidateQueries({ queryKey: queryKeys.accounts });
    },
  });
}

/**
 * openapi-typescript types a multipart file part as `string` (the OpenAPI "binary" format).
 * The request sends the File itself; `toFormData` passes it through untouched.
 */
function filePart(file: File): string {
  return file as unknown as string;
}

function toFormData(body: Record<string, string | number | null | undefined>): FormData {
  const form = new FormData();
  for (const [name, value] of Object.entries(body)) {
    if (value === null || value === undefined) continue;
    form.append(name, typeof value === "number" ? String(value) : value);
  }
  return form;
}

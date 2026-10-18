import { useRef, type ComponentProps } from "react";

import { Button } from "@/components/ui/button";
import { STATEMENT_ACCEPT } from "@/screens/import/files";

type FileInputButtonProps = Omit<ComponentProps<typeof Button>, "onClick" | "type"> & {
  onFiles: (files: File[]) => void;
};

/** A button that opens the system file picker for a statement. */
export function FileInputButton({ onFiles, children, ...buttonProps }: FileInputButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <Button type="button" {...buttonProps} onClick={() => inputRef.current?.click()}>
        {children}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept={STATEMENT_ACCEPT}
        hidden
        aria-label="Statement file"
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          // Cleared so choosing the same file again still counts as a change.
          event.currentTarget.value = "";
          if (files.length > 0) onFiles(files);
        }}
      />
    </>
  );
}

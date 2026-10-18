import { useQueryClient } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { useId, useState, type SubmitEvent } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { paths } from "@/paths";
import { useEraseData } from "@/screens/settings/queries";
import { SettingsSection } from "@/screens/settings/SettingsSection";

/** What the user types to enable the button; the engine requires the same word. */
const CONFIRMATION = "DELETE";

/** The danger zone: erase every piece of data, gated by typing DELETE. */
export function DeleteEverythingCard() {
  const eraseData = useEraseData();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  const ids = { input: useId(), hint: useId() };
  const confirmed = typed === CONFIRMATION;

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed || eraseData.isPending) return;
    eraseData.mutate(undefined, {
      onSuccess: () => {
        // Every cached answer describes data that no longer exists.
        queryClient.clear();
        toast.success("All your data was deleted.");
        void navigate(paths.welcome, { replace: true });
      },
    });
  }

  return (
    <SettingsSection
      title="Delete everything"
      tone="danger"
      icon={TriangleAlert}
      description="Permanently deletes every account, import and transaction, along with the categories, rules and merchant names Monelyth has learned. Export first if you might want any of it back."
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <Label htmlFor={ids.input}>Type {CONFIRMATION} to confirm</Label>
        <div className="flex flex-wrap items-center gap-3">
          <Input
            id={ids.input}
            value={typed}
            onChange={(event) => {
              setTyped(event.target.value);
            }}
            aria-describedby={ids.hint}
            className="max-w-48 font-mono"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            disabled={eraseData.isPending}
          />
          <Button type="submit" variant="destructive" disabled={!confirmed || eraseData.isPending}>
            {eraseData.isPending ? "Deleting…" : "Delete everything"}
          </Button>
        </div>
        <p id={ids.hint} className="text-muted-foreground text-xs">
          In capital letters. This can't be undone.
        </p>
        {eraseData.isError ? (
          <p role="alert" className="text-destructive text-sm">
            {eraseData.error.message}
          </p>
        ) : null}
      </form>
    </SettingsSection>
  );
}

import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { suggestionCount } from "@/screens/review/format";
import { useAcceptAllSuggestions } from "@/screens/review/queries";

interface AcceptAllDialogProps {
  open: boolean;
  /** How many suggestions are waiting, as shown on the button that opened this. */
  count: number;
  onOpenChange: (open: boolean) => void;
}

/** Confirm, then accept every suggestion in the review queue at once. */
export function AcceptAllDialog({ open, count, onOpenChange }: AcceptAllDialogProps) {
  const acceptAll = useAcceptAllSuggestions();

  function handleOpenChange(next: boolean) {
    // Closing mid-request would hide the outcome; the buttons are disabled meanwhile too.
    if (!next && acceptAll.isPending) return;
    if (!next) acceptAll.reset();
    onOpenChange(next);
  }

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Accept all {suggestionCount(count)}?</AlertDialogTitle>
          <AlertDialogDescription>
            Each suggested category becomes your choice and is remembered for its merchant. You can
            still change any of them later. Transactions without a suggestion stay in review.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {acceptAll.isError ? (
          <p role="alert" className="text-destructive text-sm">
            {acceptAll.error.message}
          </p>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={acceptAll.isPending}>Cancel</AlertDialogCancel>
          {/* A plain button, not AlertDialogAction, so the dialog stays open until the
              engine confirms (or shows why it couldn't). */}
          <Button
            disabled={acceptAll.isPending}
            onClick={() => {
              acceptAll.mutate(undefined, {
                onSuccess: ({ accepted }) => {
                  toast.success(`Accepted ${suggestionCount(accepted)}`);
                  acceptAll.reset();
                  onOpenChange(false);
                },
              });
            }}
          >
            {acceptAll.isPending ? "Accepting…" : "Accept all"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

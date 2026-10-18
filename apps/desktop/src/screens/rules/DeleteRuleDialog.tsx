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
import { useDeleteRule, type Rule } from "@/screens/rules/queries";

interface DeleteRuleDialogProps {
  /** The rule to delete; the dialog is open while this is set. */
  rule: Rule | null;
  onClose: () => void;
}

export function DeleteRuleDialog({ rule, onClose }: DeleteRuleDialogProps) {
  const deleteRule = useDeleteRule();

  function handleOpenChange(open: boolean) {
    // Closing mid-request would hide the outcome; the buttons are disabled meanwhile too.
    if (!open && !deleteRule.isPending) {
      deleteRule.reset();
      onClose();
    }
  }

  return (
    <AlertDialog open={rule !== null} onOpenChange={handleOpenChange}>
      {rule ? (
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete the rule for “{rule.pattern}”?</AlertDialogTitle>
            <AlertDialogDescription>
              The transactions it categorized are categorized again without it. Categories you set
              yourself stay as they are.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteRule.isError ? (
            <p role="alert" className="text-destructive text-sm">
              {deleteRule.error.message}
            </p>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteRule.isPending}>Cancel</AlertDialogCancel>
            {/* A plain button, not AlertDialogAction, so the dialog stays open until the
                engine confirms (or shows why it couldn't). */}
            <Button
              variant="destructive"
              disabled={deleteRule.isPending}
              onClick={() => {
                deleteRule.mutate(rule.id, {
                  onSuccess: () => {
                    toast.success("Rule deleted");
                    deleteRule.reset();
                    onClose();
                  },
                });
              }}
            >
              {deleteRule.isPending ? "Deleting…" : "Delete rule"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      ) : null}
    </AlertDialog>
  );
}

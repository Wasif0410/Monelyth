import { toast } from "sonner";

import type { Account } from "@/api/queries";
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
import { useDeleteAccount } from "@/screens/accounts/queries";
import { deletionSummary } from "@/screens/accounts/text";

interface DeleteAccountDialogProps {
  /** The account to delete; the dialog is open while this is set. */
  account: Account | null;
  onClose: () => void;
}

export function DeleteAccountDialog({ account, onClose }: DeleteAccountDialogProps) {
  const deleteAccount = useDeleteAccount();

  function handleOpenChange(open: boolean) {
    // Closing mid-request would hide the outcome; the buttons are disabled meanwhile too.
    if (!open && !deleteAccount.isPending) {
      deleteAccount.reset();
      onClose();
    }
  }

  function handleDelete(target: Account) {
    deleteAccount.mutate(target.id, {
      onSuccess: () => {
        toast.success(`Deleted ${target.name}`);
        deleteAccount.reset();
        onClose();
      },
    });
  }

  return (
    <AlertDialog open={account !== null} onOpenChange={handleOpenChange}>
      {account ? (
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {account.name}?</AlertDialogTitle>
            <AlertDialogDescription>{deletionSummary(account)}</AlertDialogDescription>
          </AlertDialogHeader>
          {deleteAccount.isError ? (
            <p role="alert" className="text-destructive text-sm">
              {deleteAccount.error.message}
            </p>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteAccount.isPending}>Cancel</AlertDialogCancel>
            {/* A plain button, not AlertDialogAction, so the dialog stays open until the
                engine confirms (or shows why it couldn't). */}
            <Button
              variant="destructive"
              disabled={deleteAccount.isPending}
              onClick={() => {
                handleDelete(account);
              }}
            >
              {deleteAccount.isPending ? "Deleting…" : "Delete account"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      ) : null}
    </AlertDialog>
  );
}

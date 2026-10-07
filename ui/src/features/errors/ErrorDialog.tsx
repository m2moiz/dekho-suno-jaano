import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { type AppError, copyText, dismissError, useShownError } from "./appError";

type Copied = "idle" | "copied" | "failed";

/**
 * One error, as a sentence, with a button that copies it whole (#82).
 *
 * `onReload` adds a reload button, for a view that crashed and cannot carry
 * on. Without `onClose` the dialog cannot be dismissed: a crashed view has
 * nothing behind it to go back to.
 */
export function ErrorDialog({
  error,
  onClose,
  onReload,
}: {
  error: AppError;
  onClose?: () => void;
  onReload?: () => void;
}) {
  const [copied, setCopied] = useState<Copied>("idle");
  const copy = () => {
    navigator.clipboard.writeText(copyText(error)).then(
      () => setCopied("copied"),
      () => setCopied("failed"),
    );
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose?.();
      }}
      disablePointerDismissal={onClose === undefined}
    >
      <DialogContent showCloseButton={false} className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Something went wrong</DialogTitle>
          <DialogDescription className="text-foreground select-text">
            {error.message}
          </DialogDescription>
        </DialogHeader>
        <p className="font-mono text-xs text-muted-foreground select-text">
          {error.error}
          {error.request !== null && <> &middot; {error.request}</>}
        </p>
        <DialogFooter>
          {copied === "failed" && (
            <span className="self-center text-xs text-muted-foreground">
              The clipboard refused; select the text above instead.
            </span>
          )}
          <Button variant="outline" onClick={copy}>
            {copied === "copied" ? "Copied" : "Copy error"}
          </Button>
          {onReload !== undefined && <Button onClick={onReload}>Reload</Button>}
          {onClose !== undefined && onReload === undefined && (
            <Button onClick={onClose}>Close</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const RELOAD_ONLY = new Set(["TranscriptChanged", "ListChanged", "ReviewChanged"]);

/** Whatever showError() last raised, until it is closed. */
export function ShownErrorDialog() {
  const error = useShownError();
  if (error === null) return null;
  // The transcript was made again under the page (#249), or its edits or its
  // review were changed in another tab (#251): the only way on is a reload.
  const reload = RELOAD_ONLY.has(error.error) ? () => window.location.reload() : undefined;
  return <ErrorDialog error={error} onClose={dismissError} onReload={reload} />;
}

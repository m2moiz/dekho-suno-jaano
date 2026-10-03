import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = {
  /** The words as the recogniser wrote them. */
  heard: string;
  /** Where the stretch starts and ends in the recording, for the description. */
  from: string;
  to: string;
  onSave: (text: string) => void;
  onClose: () => void;
};

/**
 * Retype what was actually said (#83). The words keep the same stretch of
 * the recording; an empty box leaves it as audio with no words.
 */
export function CorrectDialog({ heard, from, to, onSave, onClose }: Props) {
  const [text, setText] = useState(heard);
  const save = (event: FormEvent) => {
    event.preventDefault();
    onSave(text);
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={save} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Correct the words</DialogTitle>
            <DialogDescription>
              From {from} to {to}. What you type keeps that stretch of the recording; the words
              around it do not move. Leave it empty if nothing was said there.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="correction">What was said</Label>
            <Input
              id="correction"
              dir="auto"
              autoFocus
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={text.trim() === heard.trim()}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Props = {
  label: string;
  name: string;
  onRename: (label: string, name: string) => void;
};

/**
 * A speaker's nameplate, renamable where it stands (Hashiya spec, Reader:
 * "click a nameplate, type a name"; critique: "Speaker N not nameable").
 * Enter keeps the name, Esc or leaving the field keeps the old one, and an
 * emptied field gives the speaker its own label back. It reads as the name in
 * the speaker's colour, not as a button (transcript.css, `button.nameplate`).
 */
export function Nameplate({ label, name, onRename }: Props) {
  const [editing, setEditing] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  // Enter and Esc hand focus back to the nameplate; leaving the field by
  // clicking elsewhere leaves it where the click put it.
  const refocus = useRef(false);
  useEffect(() => {
    if (editing || !refocus.current) return;
    refocus.current = false;
    button.current?.focus();
  }, [editing]);
  const close = () => {
    refocus.current = true;
    setEditing(false);
  };
  if (!editing) {
    return (
      <Button ref={button} variant="ghost" className="nameplate" aria-label={`${name}, rename`} onClick={() => setEditing(true)}>
        {name}
      </Button>
    );
  }
  return (
    <Input
      autoFocus
      aria-label={`Name for ${name}`}
      defaultValue={name}
      dir="auto"
      spellCheck={false}
      className="nameplate bg-card dark:bg-card"
      onFocus={(event) => event.currentTarget.select()}
      onBlur={() => setEditing(false)}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          onRename(label, event.currentTarget.value);
          close();
        } else if (event.key === "Escape") {
          event.preventDefault();
          close();
        }
      }}
    />
  );
}

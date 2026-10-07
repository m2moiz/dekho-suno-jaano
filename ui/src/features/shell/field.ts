/**
 * A quiet button on the blue field (the bar, the rail): the ghost variant's
 * pale hover and open fills would leave its light text unreadable there, in
 * the dark scheme too, so each is a faint wash of white instead.
 */
export const FIELD_BUTTON =
  "text-field-foreground hover:bg-white/10 hover:text-field-foreground aria-expanded:bg-white/10 aria-expanded:text-field-foreground dark:hover:bg-white/10";

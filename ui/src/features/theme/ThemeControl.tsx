import { useState } from "react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { readTheme, saveTheme, THEMES, type Theme } from "./theme";

const LABELS: Record<Theme, string> = { light: "Light", dark: "Dark", system: "System" };

/** Light / Dark / System, starting on whatever was saved, else System. */
export function ThemeControl() {
  const [theme, setTheme] = useState<Theme>(() => readTheme());
  return (
    <ToggleGroup
      aria-label="Colours"
      variant="outline"
      size="sm"
      spacing={0}
      value={[theme]}
      onValueChange={(picked: string[]) => {
        // Pressing the one already on would leave none on; keep it instead.
        const next = THEMES.find((t) => t === picked[0]);
        if (next === undefined) return;
        setTheme(next);
        saveTheme(next);
      }}
    >
      {THEMES.map((value) => (
        <ToggleGroupItem key={value} value={value}>
          {LABELS[value]}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

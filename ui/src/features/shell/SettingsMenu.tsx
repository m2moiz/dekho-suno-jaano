import { Settings2 } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { readTheme, saveTheme, THEMES, type Theme } from "@/features/theme/theme";
import { FIELD_BUTTON } from "./field";

const LABELS: Record<Theme, string> = { light: "Light", dark: "Dark", system: "Same as the Mac" };

/**
 * The bar's one settings menu: colours (Light / Dark / follow the Mac, #116),
 * and whatever the page adds below it (Task 3 adds the key sheet). A menu,
 * not three buttons in the bar, so the bar holds only what the page is for.
 */
export function SettingsMenu({ extra }: { extra?: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => readTheme());
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label="Settings"
            className={`size-11 ${FIELD_BUTTON}`}
          />
        }
      >
        <Settings2 aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Colours</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={theme}
            onValueChange={(picked: string) => {
              const next = THEMES.find((t) => t === picked);
              if (next === undefined) return;
              setTheme(next);
              saveTheme(next);
            }}
          >
            {THEMES.map((value) => (
              <DropdownMenuRadioItem key={value} value={value} className="min-h-11 sm:min-h-8">
                {LABELS[value]}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        {extra}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

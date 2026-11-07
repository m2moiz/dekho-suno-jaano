import { useEffect, useState } from "react";

import { DropdownMenuCheckboxItem, DropdownMenuGroup, DropdownMenuLabel, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { DEFAULTS, loadSettings, saveSettings, type Settings } from "./settings";

type Format = Settings["export_formats"][number];
const FORMATS: readonly { format: Format; label: string }[] = [
  { format: "srt", label: "SRT subtitles" },
  { format: "vtt", label: "WebVTT subtitles" },
  { format: "txt", label: "Plain text" },
];

/**
 * The auto-export's settings (#132), in the settings menu: which formats a
 * finished transcription is also written as, beside its recording, and
 * whether a file already there is written over. Read from the server when
 * the menu opens and kept there, so every launch and every page agrees.
 */
export function ExportSettings() {
  const [kept, setKept] = useState<Settings>(DEFAULTS);
  useEffect(() => {
    let live = true;
    void loadSettings().then((found) => {
      if (live) setKept(found);
    });
    return () => {
      live = false;
    };
  }, []);
  const change = (next: Partial<Settings>) => {
    setKept((now) => ({ ...now, ...next }));
    void saveSettings(next);
  };
  const toggle = (format: Format, on: boolean) => {
    const formats = FORMATS.map((f) => f.format).filter((f) => (f === format ? on : kept.export_formats.includes(f)));
    change({ export_formats: formats });
  };
  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuGroup>
        <DropdownMenuLabel>After a transcription, also write</DropdownMenuLabel>
        {FORMATS.map(({ format, label }) => (
          <DropdownMenuCheckboxItem
            key={format}
            checked={kept.export_formats.includes(format)}
            onCheckedChange={(on: boolean) => toggle(format, on)}
            closeOnClick={false}
            className="min-h-11 sm:min-h-8"
          >
            {label}, beside the recording
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuCheckboxItem
          checked={kept.export_overwrite}
          onCheckedChange={(on: boolean) => change({ export_overwrite: on })}
          closeOnClick={false}
          className="min-h-11 sm:min-h-8"
        >
          Write over a file already there
        </DropdownMenuCheckboxItem>
      </DropdownMenuGroup>
    </>
  );
}

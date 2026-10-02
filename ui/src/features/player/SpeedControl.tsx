import { type RefObject, useEffect, useState } from "react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { applySpeed, readSpeed, saveSpeed, type Speed, SPEEDS, speedLabel } from "./speed";

const ITEMS = SPEEDS.map((value) => ({ value, label: speedLabel(value) }));

/**
 * 0.5x to 2x for the one media element the playhead reads (#81). The playhead
 * reads that element's own currentTime every frame, so the highlight keeps
 * time at any speed with nothing to tell it.
 */
export function SpeedControl({ media }: { media: RefObject<HTMLMediaElement | null> }) {
  const [speed, setSpeed] = useState<Speed>(() => readSpeed());

  useEffect(() => {
    if (media.current !== null) applySpeed(media.current, speed);
  }, [media, speed]);

  return (
    <Select
      items={ITEMS}
      value={speed}
      onValueChange={(picked) => {
        const next = SPEEDS.find((s) => s === picked);
        if (next === undefined) return;
        setSpeed(next);
        saveSpeed(next);
      }}
    >
      <SelectTrigger size="sm" aria-label="Playback speed" className="w-20">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {ITEMS.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

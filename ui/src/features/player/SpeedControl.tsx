import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FIELD_BUTTON, FIELD_EDGE } from "@/features/shell/field";
import { type Speed, SPEEDS, speedLabel } from "./speed";

const ITEMS = SPEEDS.map((value) => ({ value, label: speedLabel(value) }));

/**
 * 0.5x to 2x (#81). The Player owns the speed now, because Review changes it
 * from the keyboard (Ctrl+, and Ctrl+.) and this select must show that.
 */
export function SpeedControl({ speed, onSpeed }: { speed: Speed; onSpeed: (speed: Speed) => void }) {
  return (
    <Select
      items={ITEMS}
      value={speed}
      onValueChange={(picked) => {
        const next = SPEEDS.find((s) => s === picked);
        if (next !== undefined) onSpeed(next);
      }}
    >
      <SelectTrigger
        size="sm"
        aria-label="Playback speed"
        // 44 px on a phone, 36 on a laptop; the primitive's own data-[size=sm]:h-7 is
        // the same variant, so these replace it.
        className={`w-20 tabular-nums data-[size=sm]:h-11 sm:data-[size=sm]:h-9 dark:bg-transparent ${FIELD_EDGE} ${FIELD_BUTTON}`}
      >
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

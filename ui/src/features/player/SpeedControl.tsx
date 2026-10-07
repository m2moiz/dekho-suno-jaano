import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
        className="h-11 w-20 border-white/20 bg-transparent text-field-foreground tabular-nums"
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

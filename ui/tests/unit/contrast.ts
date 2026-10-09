// WCAG 2 contrast for the colours the stylesheets write: `#rrggbb` and
// `oklch(l c h)`. Hex through the sRGB transfer curve; oklch -> OKLab ->
// linear sRGB per Björn Ottosson's published matrices. Shared by
// palette.test.ts and confidence.test.tsx, so a colour changed in a
// stylesheet is checked where it is used.

function srgb(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function fromOklch(l: number, c: number, h: number): [number, number, number] {
  const a = c * Math.cos((h * Math.PI) / 180);
  const b = c * Math.sin((h * Math.PI) / 180);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (x: number) => Math.min(1, Math.max(0, x));
  return [
    clamp(4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_),
    clamp(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_),
    clamp(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_),
  ];
}

/** Relative luminance of `#rrggbb` or `oklch(l c h)`. */
export function luminance(colour: string): number {
  const text = colour.trim();
  const hex = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(text);
  let rgb: [number, number, number];
  if (hex !== null) {
    rgb = [srgb(parseInt(hex[1] ?? "0", 16)), srgb(parseInt(hex[2] ?? "0", 16)), srgb(parseInt(hex[3] ?? "0", 16))];
  } else {
    const found = /^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/.exec(text);
    if (found === null) throw new Error(`not a colour this helper reads: ${colour}`);
    rgb = fromOklch(Number(found[1]), Number(found[2]), Number(found[3]));
  }
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
}

/** The two halves of `light-dark(x, y)`, split at the comma outside any parentheses. */
function halves(value: string): [string, string] {
  const inner = value.trim().replace(/^light-dark\(/, "").replace(/\)$/, "");
  let depth = 0;
  for (let i = 0; i < inner.length; i += 1) {
    const ch = inner[i];
    if (ch === "(") depth += 1;
    else if (ch === ")") depth -= 1;
    else if (ch === "," && depth === 0) return [inner.slice(0, i).trim(), inner.slice(i + 1).trim()];
  }
  throw new Error(`no light-dark pair in ${value}`);
}

/** One scheme's side of `--name` as `css` declares it: the value itself, or its light or dark half. */
export function token(css: string, name: string, scheme: "light" | "dark"): string {
  const found = new RegExp(`(?:^|[\\s;{])${name.replace(/[-]/g, "\\-")}:\\s*([^;]+);`, "m").exec(css);
  if (found?.[1] === undefined) throw new Error(`${name} is not declared`);
  const value = found[1].trim();
  if (!value.startsWith("light-dark(")) return value;
  const [light, dark] = halves(value);
  return scheme === "light" ? light : dark;
}

/** The light and dark colours inside `light-dark(...)` on the line declaring `property` after `selector`. */
export function pair(css: string, selector: string, property: string): [string, string] {
  const block = css.slice(css.indexOf(selector));
  const line = new RegExp(`${property}:\\s*(light-dark\\([^;]+\\));`).exec(block)?.[1];
  if (line === undefined) throw new Error(`no light-dark pair for ${property} in ${selector}`);
  return halves(line);
}

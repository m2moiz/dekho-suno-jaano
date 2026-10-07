import { ArrowLeft } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";

import { FIELD_BUTTON } from "./field";
import { SettingsMenu } from "./SettingsMenu";

// The custom property on <html> holding the bar's height, which the page's
// top scroll padding reads (index.css), so a word the browser scrolls into
// view (a Cmd+F match, #230) never lands under the bar.
export const BAR_HEIGHT = "--dsj-bar-height";

/**
 * The blue field's top half (Hashiya spec, "Colour owns regions"): the
 * wordmark on the library, a way back everywhere else, then the page's own
 * tools, then settings. It wraps to a second row on a phone rather than
 * squeezing its targets under 44 px.
 */
export function AppBar({
  back = false,
  children,
  settings,
  measure = "max-w-6xl",
}: {
  back?: boolean;
  children?: ReactNode;
  settings?: ReactNode;
  /** The bar content's max width, so a page can line it up with its own column. */
  measure?: string;
}) {
  const bar = useRef<HTMLElement>(null);
  useEffect(() => {
    const element = bar.current;
    if (element === null) return;
    const root = document.documentElement;
    const resized = new ResizeObserver(() => root.style.setProperty(BAR_HEIGHT, `${element.getBoundingClientRect().height}px`));
    resized.observe(element);
    return () => {
      resized.disconnect();
      root.style.removeProperty(BAR_HEIGHT);
    };
  }, []);
  return (
    <header ref={bar} className="sticky top-0 z-30 bg-field text-field-foreground">
      <div className={`mx-auto flex min-h-14 w-full ${measure} flex-wrap items-center gap-x-2 gap-y-1 px-2 py-1.5 sm:px-6`}>
        {back ? (
          <a
            href="/"
            aria-label="Library"
            className={`inline-flex size-11 shrink-0 items-center justify-center rounded-lg ${FIELD_BUTTON}`}
          >
            <ArrowLeft aria-hidden className="size-5" />
          </a>
        ) : (
          <a href="/" className="px-2 font-reading text-2xl font-semibold tracking-tight">
            dsj
          </a>
        )}
        {children}
        <div className="ml-auto">
          <SettingsMenu extra={settings} />
        </div>
      </div>
    </header>
  );
}

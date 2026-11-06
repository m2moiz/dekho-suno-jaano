// A finished job says so when the window is not looking (#130): a native
// notification and a short chime, both only when the page is in the
// background, because a person watching the row already sees it finish.
//
// One place, on purpose: in a tab this is the browser's Notification API, whose
// permission prompt is the browser's own; the Mac app (#74) swaps this file for
// its own notifier and nothing else changes. Everything here is written never
// to throw: a denied or missing permission, a browser with no Notification
// class, or an audio context the page cannot make, all degrade to silence.
//
// The chime is two sine notes from Web Audio rather than a sound file (the
// donor ships assets/success.mp3): nothing to commit, nothing to load, and the
// page already runs an AudioContext for the bleep preview.

/** What finished: the kind of job and what to call it. */
export type Finished = { kind: "transcription" | "render"; name: string; outcome: "done" | "failed" };

export type Notifier = {
  /** Whether a notification may be shown: "granted", "denied" or "default" (not asked yet). */
  permission: () => NotificationPermission | null;
  /** Ask once; resolves to the answer or null where there is no Notification API. */
  ask: () => Promise<NotificationPermission | null>;
  /** Show one; may throw, the caller catches. */
  show: (title: string, body: string) => void;
  /** Whether the window has the person's attention right now. */
  focused: () => boolean;
  /** Play the chime; may throw, the caller catches. */
  chime: () => void;
};

const SOUND_NOTES_HZ = [660, 880];
const SOUND_NOTE_S = 0.12;

let sound: AudioContext | null = null;

function playChime(): void {
  sound ??= new AudioContext();
  const context = sound;
  if (context.state === "suspended") void context.resume();
  const at = context.currentTime;
  SOUND_NOTES_HZ.forEach((hz, i) => {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.frequency.value = hz;
    const start = at + i * SOUND_NOTE_S;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.2, start + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + SOUND_NOTE_S);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + SOUND_NOTE_S);
  });
}

/** The browser's own notifier: the Notification API, the document's focus, Web Audio. */
export const browserNotifier: Notifier = {
  permission: () => (typeof Notification === "undefined" ? null : Notification.permission),
  ask: async () => {
    if (typeof Notification === "undefined") return null;
    try {
      return await Notification.requestPermission();
    } catch {
      return null;
    }
  },
  show: (title, body) => {
    // eslint-disable-next-line no-new -- the Notification constructor is how one is shown
    new Notification(title, { body });
  },
  focused: () => document.hasFocus(),
  chime: playChime,
};

/** Ask for permission the first time a job starts, so the answer is in before it finishes. Never throws. */
export async function askToNotify(notifier: Notifier = browserNotifier): Promise<void> {
  try {
    if (notifier.permission() === "default") await notifier.ask();
  } catch {
    // A refusal, or no API: the finish is still shown on the page.
  }
}

/** The words a notification uses for `finished`. */
export function words(finished: Finished): { title: string; body: string } {
  const what = finished.kind === "render" ? "Bleep render" : "Transcription";
  return finished.outcome === "done"
    ? { title: `${what} finished`, body: finished.name }
    : { title: `${what} failed`, body: finished.name };
}

/**
 * Tell the person `finished` has, if the window is not looking. Returns whether
 * anything was shown. Never throws.
 */
export function notifyFinished(finished: Finished, notifier: Notifier = browserNotifier): boolean {
  try {
    if (notifier.focused()) return false;
  } catch {
    return false;
  }
  let shown = false;
  try {
    if (notifier.permission() === "granted") {
      const { title, body } = words(finished);
      notifier.show(title, body);
      shown = true;
    }
  } catch {
    // Denied between the check and the call, or a browser that refuses: silence.
  }
  if (finished.outcome === "done") {
    try {
      notifier.chime();
    } catch {
      // No audio: the notification, if any, still stands.
    }
  }
  return shown;
}

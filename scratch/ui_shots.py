"""Screenshots of `dsj ui` for a UI task's look check: laptop and phone, light and dark.

Every UI task in docs/superpowers/plans/2026-10-07-hashiya-review-mode.md ends
with this, after `just ui-build`, because `dsj ui` serves the committed build.

It never touches the owner's library or word list. It builds a library of
its own under /tmp/dsj-shots/library/ from tones ffmpeg makes and three
transcripts made up here (English, Urdu script, and Roman Urdu with English
inside it), plus one recording with no transcript so the Transcribe dialog is
reachable. It starts `dsj ui --print-url` on that library and drives
agent-browser through each page at 1440x900 and 390x844 in light and dark. The
token URL the server prints is read from its stdout into this process and
handed to agent-browser; it is never printed, logged or written to a file, and
any agent-browser error is shown with the token cut out.

    uv run python scratch/ui_shots.py --label t3 library reader reader-urdu
    # -> /tmp/dsj-shots/t3/<page>-<w>x<h>-<scheme>.png, one path a line
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
OUT = Path("/tmp/dsj-shots")
VIEWPORTS = ((1440, 900), (390, 844))
SCHEMES = ("light", "dark")

# Made up for this script; no line comes from a recording.
SENTENCES: dict[str, list[list[str]]] = {
    "english": [
        [" See", " this", " column", " here."],
        [" It", " moved", " again", " today."],
        [" Fine,", " then", " we", " ship", " it."],
    ],
    "urdu": [
        [" آج", " صبح", " ہم", " نے", " نیا", " منصوبہ", " دیکھا۔"],  # noqa: RUF001
        [" میں", " نے", " 3", " بجے", " meeting", " رکھی", " ہے۔"],  # noqa: RUF001
        [" یہ", " بات", " ٹھیک", " ہے،", " لیکن", " وقت", " کم", " ہے۔"],  # noqa: RUF001
    ],
    "mixed": [
        [" Yaar,", " kal", " ki", " meeting", " 10", " baje", " hai."],
        [" Theek", " hai,", " main", " slides", " bana", " deta", " hoon."],
        [" Aur", " budget", " ka", " kya", " scene", " hai?"],
    ],
}
# Words given a low confidence, so the unsure count has something to count.
UNSURE = {"scene", "منصوبہ", "moved"}
MODELS = {
    "english": ("parakeet", "mlx-community/parakeet-tdt-0.6b-v3"),
    "urdu": ("whisper", "mlx-community/whisper-large-v3-turbo"),
    "mixed": ("whisper", "mlx-community/whisper-large-v3-turbo"),
}


def transcript(audio: Path, kind: str) -> dict[str, Any]:
    """Twelve sentences between two speakers, each word 0.35 s long and 0.5 s apart."""
    t = 0.3
    sentences: list[dict[str, Any]] = []
    for i, words in enumerate(SENTENCES[kind] * 4):
        tokens: list[dict[str, Any]] = []
        for w in words:
            c = 0.25 if w.strip(" .,?۔،") in UNSURE else 0.95  # noqa: RUF001
            tokens.append({"t": round(t, 3), "e": round(t + 0.35, 3), "w": w, "c": c})
            t += 0.5
        t += 0.4
        sentences.append({
            "start": tokens[0]["t"], "end": tokens[-1]["e"], "speaker": i % 2,
            "text": "".join(x["w"] for x in tokens), "tokens": tokens,
        })
    engine, model = MODELS[kind]
    return {
        "audio": str(audio), "engine": engine, "model": model,
        "speakers": ["SPEAKER_00", "SPEAKER_01"], "diarization": "senko 0.1.0",
        "text": "", "unclear": [], "sentences": sentences,
    }


def tone(path: Path, seconds: int) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"sine=frequency=330:duration={seconds}", str(path)],
        check=True,
    )


def seed(root: Path) -> dict[str, tuple[int, int]]:
    """A fresh library under `root`: one recording and one transcript per kind, and one bare recording."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    os.environ["DSJ_LIBRARY"] = str(root / "library.db")
    from dsj.ui.store import Library  # after DSJ_LIBRARY is set

    ids: dict[str, tuple[int, int]] = {}
    # A second apart, or the library would rightly file equal tones as one recording.
    for seconds, kind in enumerate(SENTENCES, start=60):
        audio = root / f"{kind}.wav"
        tone(audio, seconds)
        path = root / f"{kind}.json"
        path.write_text(json.dumps(transcript(audio, kind), ensure_ascii=False), encoding="utf-8")
        with Library.open() as library:
            adoption = library.adopt([path])
            if adoption.refused:
                raise SystemExit(f"the library refused {path}: {adoption.refused}")
            found = library.transcript(adoption.transcripts[0])
            assert found is not None
            ids[kind] = (found.recording_id, found.id)
    # A recording nobody has transcribed: the library page offers Transcribe on it.
    bare = root / "untranscribed.wav"
    tone(bare, 60 + len(SENTENCES))
    with Library.open() as library:
        library.add_recording(bare)
    return ids


QUERIES = {
    "library": lambda ids: "",
    "transcribe": lambda ids: "",
    "bleep": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "library-focus": lambda ids: "",
    "menu": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "settings": lambda ids: "",
    "reader-focus": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "reader": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "reader-urdu": lambda ids: "?recording={}&transcript={}".format(*ids["urdu"]),
    "reader-english": lambda ids: "?recording={}&transcript={}".format(*ids["english"]),
    "reader-tools": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "reader-correct": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "keys": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "review": lambda ids: "?recording={}&transcript={}&review=1".format(*ids["mixed"]),
}

# What to do on a page before its shot. Base UI's menus open on the pointer
# events a real click starts with, so a menu is pressed with all of them.
PRESS = (
    "const press = (el) => { for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) "
    "el?.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerType: 'mouse', button: 0 })); };"
)
# Keys to press on a page before its shot: two Tabs land on the bar's second control.
KEYS = {
    "library-focus": ["Tab", "Tab"],
    # Backwards from the page's start: the rail's speed, its waveform, then its Play button.
    "reader-focus": ["Shift+Tab", "Shift+Tab", "Shift+Tab"],
}
# Select one word of the transcript, as a double-click would (Task 3).
SELECT = (
    "const select = (word) => { for (const p of document.querySelectorAll('article p')) {"
    " const text = p.firstChild; const at = text.data.indexOf(word); if (at < 0) continue;"
    " const range = document.createRange(); range.setStart(text, at); range.setEnd(text, at + word.length);"
    " getSelection().removeAllRanges(); getSelection().addRange(range); return; } };"
)
ACTIONS = {
    # A word selected: its tools beside it, or above the rail on a phone (Task 3).
    "reader-tools": SELECT + "select('slides');",
    # Then Correct: the field laid over the word (Task 3).
    "reader-correct": PRESS + SELECT + "select('slides');"
    "setTimeout(() => press(Array.from(document.querySelectorAll('[role=toolbar][aria-label=Selection] button'))"
    ".find((b) => b.textContent.trim() === 'Correct')), 300);",
    # The key sheet behind `?` (Task 3).
    "keys": "document.body.dispatchEvent(new KeyboardEvent('keydown',"
    " { key: '?', code: 'Slash', shiftKey: true, bubbles: true }));",
    # The bar's settings menu, open (Task 2).
    "settings": PRESS + "press(document.querySelector('button[aria-label=Settings]'));",
    # The untranscribed recording's Transcribe dialog (Task 9).
    "transcribe": PRESS + "press(Array.from(document.querySelectorAll('button')).find((b) => b.textContent.trim() === 'Transcribe'));",
    # The reader's menu, open (Tasks 4 and 6).
    "menu": PRESS + "press(document.querySelector('button[aria-label=More]'));",
    # The reader's menu, then Bleep: the drawer (Task 4).
    "bleep": PRESS + "press(document.querySelector('button[aria-label=More]'));"
    "setTimeout(() => press(Array.from(document.querySelectorAll('[role=menuitem]'))"
    ".find((el) => el.textContent.trim().startsWith('Bleep'))), 300);",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="a folder name under /tmp/dsj-shots/")
    parser.add_argument("pages", nargs="+", choices=sorted(QUERIES))
    args = parser.parse_args()
    out = OUT / args.label
    out.mkdir(parents=True, exist_ok=True)
    root = OUT / "library"
    ids = seed(root)
    server = subprocess.Popen(
        ["uv", "run", "dsj", "ui", "--print-url"], cwd=REPO,
        env={**os.environ, "DSJ_LIBRARY": str(root / "library.db"),
             "DSJ_WORDS": str(root / "words.toml")},
        stdout=subprocess.PIPE, text=True,
    )
    assert server.stdout is not None
    url = server.stdout.readline().strip()
    if not url.startswith("http://127.0.0.1:"):
        server.terminate()
        raise SystemExit("dsj ui printed no address; run `uv run dsj ui --print-url` by hand to see why")
    parts = urlsplit(url)
    token = parts.fragment

    def browse(*argv: str) -> None:
        done = subprocess.run(["agent-browser", *argv], capture_output=True, text=True)
        if done.returncode != 0:
            said = (done.stderr or done.stdout).replace(token, "<token>")[:500]
            raise SystemExit(f"agent-browser {argv[0]} failed: {said}")

    try:
        for name in args.pages:
            address = f"{parts.scheme}://{parts.netloc}/{QUERIES[name](ids)}#{token}"
            for width, height in VIEWPORTS:
                for scheme in SCHEMES:
                    browse("set", "viewport", str(width), str(height))
                    browse("set", "media", scheme)
                    # Blank first: the same address differs from the last only by its
                    # hash, which the browser takes as no navigation, so the page
                    # would keep the last shot's focus and open menus.
                    browse("open", "about:blank")
                    browse("open", address)
                    browse("wait", "1200")
                    if name in ACTIONS:
                        # A block, because a second shot of the same address does not reload
                        # the page and `const press` would be declared twice.
                        browse("eval", "{" + ACTIONS[name] + "}")
                        browse("wait", "900")
                    # Real key presses, so the browser shows its keyboard focus ring.
                    for key in KEYS.get(name, []):
                        browse("press", key)
                    if name in KEYS:
                        # The focus ring fades in (transition-all); a shot taken at
                        # once catches it half drawn.
                        browse("wait", "500")
                    shot = out / f"{name}-{width}x{height}-{scheme}.png"
                    browse("screenshot", str(shot))
                    print(shot)
    finally:
        subprocess.run(["agent-browser", "close"], capture_output=True)
        server.terminate()
        server.wait(timeout=20)


if __name__ == "__main__":
    sys.exit(main())

"""Read in a transcript someone else made: SRT, WebVTT, or a dsj transcript (#78).

dsj could only produce a transcript by running ASR, so a caption file that
already existed, or a transcript made by someone else, could not be marked with
`dsj dekho`, exported with `dsj likho`, or bleeped. This reads one into the
payload `suno` writes, and the shape it expects is the one likho writes (#54),
so a round trip through the two gives back everything the format can hold.

The format is read off the content, never the file name. A caption file saved
with the wrong suffix is ordinary, and a name is a claim where content is not.

What a format cannot say, the transcript does not claim. There is no engine key,
so, as for whisper's inferred times (#77), `model` says where the times came
from, and payload.md says what each one means:

  * `import:srt` -- an SRT cue states a span and its words and nothing finer, so
    each sentence is one token from the cue's start to its end.
  * `import:vtt` -- a WebVTT cue can carry a timestamp tag ahead of a word, so a
    tagged cue splits into word tokens timed by their tags. A tag marks a start
    only: those tokens have no `e`. An untagged cue is one token, as for SRT.

No imported token has a `c`. Nothing measured how sure anyone was.
"""

from __future__ import annotations

__all__ = ["ParhoError", "detect", "parse"]

import html
import json
import re
from typing import Any, cast

from dsj.asr import with_char_offsets

type Payload = dict[str, Any]
type Sentence = dict[str, Any]

_SRT_TIMING = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})"
)
# WebVTT allows the hours to be left out, and anything after the end time is
# cue settings (`align:start position:0%`), which place text and time nothing.
_VTT_TIMING = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s+-->\s+(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})"
)
_VTT_STAMP = re.compile(r"<(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})>")
_VTT_VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]*)>")
_TAG = re.compile(r"(<[^>]*>)")
# The label likho writes ahead of an SRT cue's words, `SPEAKER_01: `. SRT has no
# speaker field, so this is a convention and read narrowly: capitals, digits and
# underscores, then a colon and a space. `Q: ` and `JOHN: ` read as speakers
# too, which is what they are in the caption files that use them.
_SRT_LABEL = re.compile(r"([A-Z][A-Z0-9_]*): (.*)")


class ParhoError(ValueError):
    """The file is not a transcript dsj can read."""


def _seconds(h: str | None, m: str, s: str, ms: str) -> float:
    """A timestamp's parts as seconds, divided once so 61.4 comes back as 61.4."""
    return (int(h or 0) * 3_600_000 + int(m) * 60_000 + int(s) * 1000 + int(ms)) / 1000


def detect(text: str) -> str:
    """Name the format of `text`: "vtt", "srt" or "json".

    Raises:
        ParhoError: when it is none of the three.
    """
    body = text.lstrip("﻿ \t\r\n")
    if body.startswith("WEBVTT"):
        return "vtt"
    if body.startswith("{"):
        return "json"
    if _SRT_TIMING.search(body):
        return "srt"
    raise ParhoError(
        "not SRT, WebVTT or a dsj transcript: no WEBVTT header, no JSON object, "
        "and no `00:00:01,000 --> 00:00:02,000` timing line"
    )


def _cues(text: str, timing: re.Pattern[str]) -> list[tuple[float, float, str]]:
    """Every cue as (start, end, its text lines joined by a space).

    A block is a cue if it has a timing line; everything before that line is an
    index or an identifier, and a block with none is a header, a NOTE or a
    STYLE, none of which says anything.
    """
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\n[ \t]*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip("\n").split("\n")
        for i, line in enumerate(lines):
            found = timing.search(line)
            if found is None:
                continue
            g = found.groups()
            said = " ".join(part.strip() for part in lines[i + 1 :] if part.strip())
            cues.append((_seconds(*g[:4]), _seconds(*g[4:]), said))
            break
    return cues


def _sentence(
    start: float, end: float, tokens: list[dict[str, Any]], speaker: str | None
) -> tuple[Sentence, str | None] | None:
    """A sentence in suno's shape, with its speaker's label beside it, or None if silent.

    Every sentence dsj writes begins with its own space, so that sentences glue
    with nothing (dsj/suno.py:_text_from_tokens); the first token takes one.
    A single token spans its cue, so it takes the cue's end as its own.

    Empty tokens go; a token that is only a space stays, with its own time:
    parakeet times a bare space ahead of a number as a token of its own.
    """
    tokens = [t for t in tokens if t["w"]]
    if not "".join(str(t["w"]) for t in tokens).strip():
        return None
    first = str(tokens[0]["w"])
    tokens[0]["w"] = first if first[:1].isspace() else f" {first}"
    if len(tokens) == 1:
        tokens[0]["e"] = end
    text = "".join(str(t["w"]) for t in tokens)
    return (
        {"start": start, "end": end, "text": text, "tokens": with_char_offsets(tokens)},
        speaker,
    )


def _from_srt(text: str) -> list[tuple[Sentence, str | None]]:
    found: list[tuple[Sentence, str | None]] = []
    for start, end, said in _cues(text, _SRT_TIMING):
        plain = html.unescape(_TAG.sub("", said)).strip()
        label = _SRT_LABEL.fullmatch(plain)
        speaker, words = (label.group(1), label.group(2)) if label else (None, plain)
        sentence = _sentence(start, end, [{"t": start, "w": words}], speaker)
        if sentence is not None:
            found.append(sentence)
    return found


def _from_vtt(text: str) -> list[tuple[Sentence, str | None]]:
    found: list[tuple[Sentence, str | None]] = []
    for start, end, said in _cues(text, _VTT_TIMING):
        speaker: str | None = None
        tokens: list[dict[str, Any]] = [{"t": start, "w": ""}]
        for piece in _TAG.split(said):
            stamp = _VTT_STAMP.fullmatch(piece)
            voice = _VTT_VOICE.fullmatch(piece)
            if stamp is not None:
                tokens.append({"t": _seconds(*stamp.groups()), "w": ""})
            elif voice is not None:
                speaker = speaker or html.unescape(voice.group(1)).strip()
            elif not _TAG.fullmatch(piece):
                tokens[-1]["w"] += html.unescape(piece)
        # The text between two tags is the token, spaces and all, wherever the
        # file put them. Moving a trailing space onto the next word looked
        # tidier and broke dsj's own round trip: parakeet writes tokens like
        # "s " and a bare " ", and scratch/real_0806.json came back with 6 of
        # its 480 VTT cues retimed.
        sentence = _sentence(start, end, tokens, speaker)
        if sentence is not None:
            found.append(sentence)
    return found


def _from_json(text: str, audio: str) -> Payload:
    """A dsj transcript, checked for the one key everything reads, and re-pointed."""
    loaded: object = json.loads(text)
    if not isinstance(loaded, dict) or not isinstance(
        cast("Payload", loaded).get("sentences"), list
    ):
        raise ParhoError(
            "a JSON file, but not a dsj transcript: expected an object with a "
            "`sentences` list, the file `dsj suno` writes"
        )
    return {"audio": audio} | {k: v for k, v in cast("Payload", loaded).items() if k != "audio"}


def parse(text: str, audio: str) -> Payload:
    """Read `text`, whatever its format, as a transcript that indexes `audio`.

    Sentences run earliest first, as suno promises: a caption file from
    elsewhere need not. Speaker labels, when the file names any, become
    `speakers` sorted as the diarizer sorts its own, `diarization` naming the
    import, and a `speaker` on every sentence, null where its cue named nobody.
    """
    kind = detect(text)
    if kind == "json":
        return _from_json(text, audio)
    read = _from_vtt(text) if kind == "vtt" else _from_srt(text)
    read.sort(key=lambda pair: float(pair[0]["start"]))
    labels = sorted({who for _, who in read if who is not None})
    payload: Payload = {"audio": audio, "model": f"import:{kind}"}
    sentences = [s for s, _ in read]
    if labels:
        payload |= {"speakers": labels, "diarization": f"import:{kind}"}
        sentences = [
            {
                "start": s["start"],
                "end": s["end"],
                "speaker": None if who is None else labels.index(who),
                "text": s["text"],
                "tokens": s["tokens"],
            }
            for s, who in read
        ]
    return payload | {
        "text": "".join(str(s["text"]) for s in sentences).strip(),
        "sentences": sentences,
    }

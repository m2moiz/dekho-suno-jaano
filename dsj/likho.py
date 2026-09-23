"""Write a transcript out in the formats other tools read: SRT, WebVTT and text.

The transcript is JSON, so until this existed nothing but dsj and jq could read
it. On 2026-09-22 an agent asked to make one readable hand-wrote a 60-line
converter, with its own guesses at a speaker label and a timestamp format (#54).
Every agent after it would have guessed again, each a little differently.

Subtitles are one timeline. MP4 timed text, and most players, show one cue at a
time, so a cue that overlaps the next gets rewritten by whatever reads it:
exporting an early transcript to SRT and muxing it into its recording moved 22
of 480 cues (the log is on #117). Sentences do overlap. A chunk seam can time a
sentence's last word past the start of the next one, and measured on the eleven
transcripts in scratch/, 72 to 104 adjacent pairs overlap in every long
recording once sorted by start. So cues are sorted, and each ends no later than
the next begins. No other time is touched.

Word timing goes where the format has room for it. WebVTT allows a timestamp tag
inside a cue, so every word that starts later than the one before it carries
its own start. SRT has no such thing, and plain text is for reading.
"""

from __future__ import annotations

__all__ = ["EXPORTERS", "LikhoError", "to_srt", "to_txt", "to_vtt"]

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from dsj.suno import clock

type Payload = dict[str, Any]
type Sentence = dict[str, Any]


class LikhoError(ValueError):
    """The document handed to the exporter is not a transcript."""


@dataclass(frozen=True)
class _Cue:
    """A span of the subtitle timeline, in whole milliseconds, and what is said in it."""

    start_ms: int
    end_ms: int
    speaker: str | None
    sentences: list[Sentence]

    @property
    def text(self) -> str:
        return "".join(str(s["text"]) for s in self.sentences).strip()


def _ms(seconds: float) -> int:
    """Whole milliseconds, the resolution of both subtitle formats.

    Rounded once, here, before any comparison, so a clamped end and the start
    it was clamped to print as the same digits.
    """
    return round(seconds * 1000)


def _sentences(payload: object) -> list[Sentence]:
    """The sentences that say something, earliest first.

    Sorted here, not trusted: transcripts written before the sort (#53) have
    sentences out of order, and a subtitle file must not.
    """
    if not isinstance(payload, dict) or not isinstance(
        cast("Payload", payload).get("sentences"), list
    ):
        raise LikhoError(
            "not a transcript: expected a JSON object with a `sentences` list, "
            "the file `dsj suno` writes"
        )
    sentences = cast("list[Sentence]", cast("Payload", payload)["sentences"])
    spoken = [s for s in sentences if str(s.get("text", "")).strip()]
    return sorted(spoken, key=lambda s: float(s["start"]))


def _speaker(payload: Payload, sentence: Sentence) -> str | None:
    """The sentence's label, or None if labelling did not run or found nobody."""
    labels = payload.get("speakers")
    index = sentence.get("speaker")
    if labels is None or index is None:
        return None
    return str(cast("list[str]", labels)[cast("int", index)])


def _cues(payload: Payload) -> list[_Cue]:
    """One cue per sentence, on a timeline where no cue overlaps the next.

    A sentence clamped to the next start that would then last no time at all,
    because both begin on the same millisecond, is carried into the next cue
    rather than dropped: its words still reach the file. Its label survives
    only if both agree. Measured on scratch/ this never happens; it is handled
    so that it cannot lose words when it does.
    """
    sentences = _sentences(payload)
    cues: list[_Cue] = []
    carried: list[Sentence] = []
    for i, sentence in enumerate(sentences):
        group = [*carried, sentence]
        start = _ms(float(group[0]["start"]))
        end = max(_ms(float(s["end"])) for s in group)
        following = sentences[i + 1] if i + 1 < len(sentences) else None
        if following is not None:
            end = min(end, _ms(float(following["start"])))
            if end <= start:
                carried = group
                continue
        carried = []
        labels = {_speaker(payload, s) for s in group}
        cues.append(
            _Cue(start, max(end, start), labels.pop() if len(labels) == 1 else None, group)
        )
    return cues


def _stamp(ms: int, sep: str) -> str:
    """`HH:MM:SS` then `sep` then milliseconds: `,` for SRT, `.` for WebVTT."""
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, rest = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{rest:03d}"


def to_srt(payload: Payload) -> str:
    """SubRip: numbered cues, the speaker's label ahead of the words when there is one.

    SRT has no field for a speaker, so the label is written into the text as
    `SPEAKER_00: `, the form a reader of any player can follow.
    """
    blocks: list[str] = []
    for n, cue in enumerate(_cues(payload), start=1):
        said = f"{cue.speaker}: {cue.text}" if cue.speaker else cue.text
        blocks.append(
            f"{n}\n{_stamp(cue.start_ms, ',')} --> {_stamp(cue.end_ms, ',')}\n{said}\n"
        )
    return "\n".join(blocks)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _timed(sentence: Sentence, cue: _Cue, last_ms: int) -> tuple[list[str], int]:
    """A sentence's words as WebVTT, a timestamp tag ahead of each that starts later.

    A tag must fall strictly after the previous one and strictly inside its
    cue, so a word starting on the same millisecond as the last, or past an end
    the clamp pulled in, takes no tag and keeps the time before it. Tokens that
    do not spell the sentence's text exactly, which transcripts from before #106
    can hold, give the text untimed: the words a reader sees must be the text.
    """
    tokens = cast("list[dict[str, Any]]", sentence.get("tokens", []))
    spelled = all("t" in tok and "w" in tok for tok in tokens) and (
        "".join(str(tok["w"]) for tok in tokens) == sentence["text"]
    )
    if not tokens or not spelled:
        return [_escape(str(sentence["text"]))], last_ms
    pieces: list[str] = []
    for tok in tokens:
        at = _ms(float(tok["t"]))
        if last_ms < at < cue.end_ms:
            pieces.append(f"<{_stamp(at, '.')}>")
            last_ms = at
        pieces.append(_escape(str(tok["w"])))
    return pieces, last_ms


def to_vtt(payload: Payload) -> str:
    """WebVTT: each cue voiced by its speaker, each later word stamped with its start."""
    blocks = ["WEBVTT\n"]
    for cue in _cues(payload):
        pieces: list[str] = []
        last_ms = cue.start_ms
        for sentence in cue.sentences:
            timed, last_ms = _timed(sentence, cue, last_ms)
            pieces += timed
        said = "".join(pieces).lstrip()
        voice = f"<v {_escape(cue.speaker)}>" if cue.speaker else ""
        blocks.append(
            f"{_stamp(cue.start_ms, '.')} --> {_stamp(cue.end_ms, '.')}\n{voice}{said}\n"
        )
    return "\n".join(blocks)


def to_txt(payload: Payload) -> str:
    """Plain text for a person: one block per speaker turn, headed by when it began.

    A turn is a run of sentences with the same speaker. With no labels there
    are no turns to find, so each sentence is its own line with its own time,
    which keeps an hour of transcript navigable instead of one paragraph long.
    """
    sentences = _sentences(payload)
    if "speakers" not in payload:
        return "".join(
            f"[{clock(float(s['start']))}] {str(s['text']).strip()}\n" for s in sentences
        )
    turns: list[tuple[str | None, list[Sentence]]] = []
    for sentence in sentences:
        who = _speaker(payload, sentence)
        if turns and turns[-1][0] == who:
            turns[-1][1].append(sentence)
        else:
            turns.append((who, [sentence]))
    blocks: list[str] = []
    for who, said in turns:
        head = f"[{clock(float(said[0]['start']))}]" + (f" {who}" if who else "")
        blocks.append(f"{head}\n{''.join(str(s['text']) for s in said).strip()}\n")
    return "\n".join(blocks)


# The formats `dsj likho` writes, by the name `--format` takes and the suffix
# `--out` is read for.
EXPORTERS: dict[str, Callable[[Payload], str]] = {
    "srt": to_srt,
    "vtt": to_vtt,
    "txt": to_txt,
}

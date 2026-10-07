"""What the `dsj ui` server sends and accepts: the one written description of it (#155).

`just api` turns these models, through FastAPI's OpenAPI description, into
`ui/src/api/schema.d.ts`, and the page's client is typed from that file. So a
field renamed here and not in the page is a `tsc` error, not a blank column at
runtime, and `just check` fails while the generated file is out of date.

Plain pydantic, no fastapi: the store and anything else under `dsj.ui` must
import without the `ui` extra.

The two models mirror the store's rows (`dsj/ui/store.py`, `Recording` and
`Transcript`) minus the file paths of transcripts: the page asks for a
transcript by id and never handles a path to one (#156, #112). The next
describe starting a transcription from the page and watching it (#113), and
the last a transcript's edit list (#63, #66): `dsj.hatao`'s file format,
entry for entry, minus its sources' paths, which the server fills in itself.
"""

from __future__ import annotations

__all__ = [
    "EditEntry",
    "Edits",
    "EditsUpdate",
    "Engine",
    "EngineName",
    "ItemEntry",
    "Job",
    "JobState",
    "LanguageTag",
    "ListContent",
    "Match",
    "Matches",
    "NamesUpdate",
    "ParagraphEntry",
    "Recording",
    "ReferenceRequest",
    "ReferenceWritten",
    "RenderJob",
    "RenderState",
    "Review",
    "ReviewCorrection",
    "ReviewDocument",
    "ReviewFlag",
    "ReviewPass",
    "ReviewSegment",
    "SegmentState",
    "TitleUpdate",
    "TranscribeRequest",
    "Transcript",
    "WordAdded",
    "WordRequest",
]

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# dsj.asr.ENGINES, spelled out because a type cannot be built from a tuple;
# tests/test_jobs.py holds the two equal.
type EngineName = Literal["parakeet", "whisper", "sherpa"]

# What a run's status file says (dsj/suno.py, `report(` and the two documents
# transcribe() ends on), plus the page's own `starting` and `saving`
# (dsj/ui/jobs.py, Job.view).
type JobState = Literal[
    "starting", "extracting", "running", "retrying", "diarizing", "saving", "done", "failed"
]

# A render from the page (#215, dsj/ui/jobs.py Render.view): queued, writing, over.
type RenderState = Literal["starting", "rendering", "done", "failed"]


# The sha256 of a transcript JSON's bytes, as dsj/ui/edits.py transcript_sha
# writes it (#249): 64 lowercase hex digits, and nothing else, since a page's
# copy of it names the file its refused edits are kept in.
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


# What the library row calls a transcript's language (Hashiya spec, Library):
# worked out from its run and its script by dsj/ui/routes/recording.py.
type LanguageTag = Literal["urdu", "mixed", "english"]


class Transcript(BaseModel):
    """One transcript of a recording, as the library page lists it."""

    id: int
    finished_at: str
    # None for an adopted transcript that names no engine: one written before
    # #172, or imported by `dsj parho`. The model id does not say (#156).
    engine: str | None
    model: str
    # True when speaker labelling ran, False when it did not, None when unknown.
    diarized: bool | None
    speaker_count: int | None
    mark_count: int | None
    language: str | None
    # When an edit to it was last saved from the app (#83), else None.
    last_edited_at: str | None
    # Urdu, mixed or English, or None when nothing says (#245).
    language_tag: LanguageTag | None
    # How far its review got, or both None when nobody has reviewed it.
    review_checked: int | None
    review_total: int | None


class Recording(BaseModel):
    """One recording, wherever it was last seen, with every transcript of it."""

    id: int
    path: str
    size_bytes: int | None
    duration_s: float | None
    content_id: str | None
    audio_codec: str | None
    video_codec: str | None
    first_seen: str
    missing: bool
    # What ffprobe said when it could not read the file, else None (#110).
    unreadable: str | None
    # A title a person gave it, else None: the page derives one from the file's name.
    title: str | None
    transcripts: list[Transcript]


class TitleUpdate(BaseModel):
    """A recording's title; empty or None takes it away, so the page derives one again."""

    title: str | None = Field(default=None, max_length=200)


class Engine(BaseModel):
    """One engine the picker offers, and whether it can run on this machine."""

    name: EngineName
    # The sentence the engine's own available() wrote when it cannot run, else None.
    reason: str | None
    default_model: str
    # True when it sends the audio off this Mac (#247); the dialog marks it "cloud".
    cloud: bool
    # What an hour of audio costs on it in US dollars, or None when it costs nothing.
    usd_per_hour: float | None


class TranscribeRequest(BaseModel):
    """What the page sends to start a transcription: the flags of `dsj suno`, as values."""

    engine: EngineName = "parakeet"
    # Empty or absent means the engine's own default.
    model: str | None = None
    # whisper's three; parakeet refuses language and prompt, as `dsj suno` does.
    language: str | None = None
    prompt: str | None = None
    roman_urdu: bool = False
    # "Label speakers", on unless switched off: `--no-diarize` inverted.
    diarize: bool = True
    require_diarize: bool = False
    # "Start over": `--no-resume`.
    start_over: bool = False


class Job(BaseModel):
    """A transcription started from the page, as its last status frame and its outcome say."""

    id: int
    recording_id: int
    engine: EngineName
    model: str
    language: str | None
    # False for whisper unanchored: one frame at 0%, then nothing until done.
    reports_progress: bool
    started_at: str
    state: JobState
    fraction: float
    audio_done_s: float
    audio_total_s: float
    elapsed_s: float
    speed: float
    eta_s: float | None
    # Seconds ffmpeg's position has stood still, while it has (dsj/suno.py STALL_S).
    stalled_s: float | None
    error: str | None
    # The library's row for the finished transcript.
    transcript_id: int | None
    # Warnings the run logged: what it could not do, though it finished.
    notes: list[str]


class ParagraphEntry(BaseModel):
    """Opens a run of words: who said them and in which language (dsj.hatao.Paragraph)."""

    kind: Literal["paragraph"]
    speaker: str | None
    # A language tag such as "ur" or "en-GB", or None when unknown (#86).
    language: str | None


class ItemEntry(BaseModel):
    """A stretch of one source's audio and the text said in it (dsj.hatao.Item).

    The keys are the file's own, `sourceStart` included, so the page writes the
    format `dsj hatao` reads.
    """

    kind: Literal["item"]
    # The source's id in the document; the server alone knows its file.
    source: str
    sourceStart: float
    length: float
    # "" for a stretch with no words in it: a pause, or audio nobody transcribed.
    text: str
    muted: bool
    # How sure the recogniser was of the word (#62), 1.0 once a person edited
    # it, None where there is none. Not part of the file: the server works it
    # out from the transcript on every read (dsj/ui/edits.py) and ignores it
    # on a save.
    confidence: float | None


type EditEntry = Annotated[ParagraphEntry | ItemEntry, Field(discriminator="kind")]


class Edits(BaseModel):
    """A transcript's edit list as the page edits it, and what it needs beside it."""

    content: list[EditEntry]
    # The names a person gave the speakers, by label (#243); {} when none.
    names: dict[str, str]
    # How far a mute reaches past each side of a word, in seconds (dsj.hatao.PAD_S).
    pad_s: float
    # When the list was last saved, or None while it is as the transcript made it.
    edited_at: str | None
    # The stretches of the recording a render of this list silences, in
    # seconds, worked out by dsj.hatao.spans_to_mute itself, so what the page
    # plays muted is what a render mutes (#84). None when the list cannot be
    # rendered, and `unrenderable` says why.
    spans: list[tuple[float, float]] | None
    unrenderable: str | None
    # Why the saved list was put aside and this one built fresh, or None (#249).
    replaced: str | None
    # The sha256 of the transcript JSON this list goes with: the page sends it
    # back with each save, so a list loaded before the transcript was made
    # again is never saved over the new one (#249).
    transcript_sha: Sha256


class ListContent(BaseModel):
    """The page's whole edit list as it is now, for a route that reads it and saves nothing."""

    content: list[EditEntry]


class EditsUpdate(ListContent):
    """The page's whole edit list, to save in place of the one before."""

    # The sha of the transcript the page loaded the list against (Edits.transcript_sha).
    transcript_sha: Sha256


class NamesUpdate(BaseModel):
    """Every speaker's name, by label, in place of the ones before; a blank name clears one."""

    names: dict[str, str]


class Match(BaseModel):
    """One word, or phrase, a word list matched (dsj.hatao.Match)."""

    # Its entries in the edit list, [start, stop).
    start: int
    stop: int
    # As the transcript writes it.
    word: str
    # The list entry that matched it: `<list>:<name>`, the list `user` for the user's own.
    entry: str
    start_s: float
    end_s: float


class Matches(BaseModel):
    """What one pass of the word lists over an edit list found, and what it searched."""

    matches: list[Match]
    words_searched: int
    # Each list searched, by name: a shipped list's language, or `user`.
    lists: list[str]
    # The sentence `dsj hatao` prints about what the engine may have left out (#152).
    recall: str


class WordRequest(BaseModel):
    """A spelling to add to the user's own word list (#64's user file)."""

    word: str


class WordAdded(BaseModel):
    """The entry the spelling matches as, and whether the request added it."""

    entry: str
    added: bool


class RenderJob(BaseModel):
    """A bleep render started from the page (#215), as the worker last left it."""

    id: int
    transcript_id: int
    recording_id: int
    started_at: str
    state: RenderState
    fraction: float
    # Where the bleeped file goes: beside the recording, never over anything.
    output: str
    # How many stretches of the recording it silences.
    spans: int
    error: str | None
    # What it could not do, though it finished.
    notes: list[str]


# Review mode (Hashiya spec, #248). No field below has a default, on purpose:
# a model that is both sent and accepted with defaults is split by FastAPI into
# "-Input" and "-Output" schemas, and the page would have two types for one
# document. The page always sends every field.

# What a person can say about a sentence besides its words (spec, Ctrl+U and Ctrl+F).
type ReviewFlag = Literal["unclear", "not_speech", "overlap", "cut_off"]
# Every sentence in order (for answer keys), or only the likely errors.
type ReviewPass = Literal["every", "likely"]
type SegmentState = Literal["unchecked", "checked"]


class ReviewSegment(BaseModel):
    """One sentence of a review, by its span of the recording, which every edit keeps."""

    start: float
    end: float
    state: SegmentState
    flags: list[ReviewFlag]
    # The speaker label a person set for it in Review (Ctrl+1 to Ctrl+9), else None.
    speaker: str | None
    # Whether a person changed its words in Review.
    edited: bool


class ReviewCorrection(BaseModel):
    """One change of words made in Review, before and after: sub-project C's learning data."""

    at: str
    start: float
    end: float
    before: str
    after: str


class ReviewDocument(BaseModel):
    """A transcript's review: its sentences and their state, the pass, and where the person was."""

    version: Literal[1]
    # The sha256 of the transcript JSON the review was made against: when the
    # transcript is made again, the page re-checks the sentences by span.
    transcript_sha: Sha256
    review_pass: ReviewPass
    # Where the person was, in seconds, so leaving and coming back resumes there.
    cursor_s: float
    started_at: str
    updated_at: str
    segments: list[ReviewSegment]
    corrections: list[ReviewCorrection]


class Review(BaseModel):
    """A transcript's review, or None, and the sha of the transcript as it is now."""

    document: ReviewDocument | None
    transcript_sha: Sha256


class ReferenceRequest(BaseModel):
    """Save the answer key; with `allow_partial`, even while sentences are unchecked."""

    allow_partial: bool = False


class ReferenceWritten(BaseModel):
    """The answer key's files (names only, beside the transcript), and how much of it is checked."""

    files: list[str]
    segments: int
    unchecked: int

"""A checkpoint that survives a change it should not survive is worse than none.

Reusing tokens decoded from different audio, a different model, or a different
chunk geometry produces a transcript that is silently wrong -- and silently
wrong is the failure mode this whole feature exists to avoid.
"""

from __future__ import annotations

import dataclasses
import json
import struct
from pathlib import Path

import pytest

from dsj.alignment import AlignedToken
from dsj.checkpoint import (
    SCHEMA,
    Fingerprint,
    checkpoint_path_for,
    fingerprint,
    read_checkpoint,
    write_checkpoint,
)
from dsj.identity import content_id

FP = Fingerprint(
    schema=SCHEMA,
    content_id="141664974-" + "ab" * 32,
    total_samples=70_832_448,
    model_id="mlx-community/parakeet-tdt-0.6b-v3",
    chunk_s=120.0,
    overlap_s=15.0,
    engine_fields={"parakeet_version": "0.5.2"},
    media="/x/meeting.mov",
)

TOKENS = [
    AlignedToken(id=5, text=" hello", start=1.25, duration=0.32, confidence=0.91),
    AlignedToken(id=9, text=" world", start=1.57, duration=0.48, confidence=0.87),
]


def test_checkpoint_path_sits_beside_the_output(tmp_path: Path) -> None:
    assert checkpoint_path_for(tmp_path / "meeting.json") == tmp_path / "meeting.json.ckpt"


def test_round_trip_preserves_tokens_exactly(tmp_path: Path) -> None:
    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, FP, next_start=1_680_000, tokens=TOKENS)

    got = read_checkpoint(p, FP)
    assert got is not None
    next_start, tokens = got
    assert next_start == 1_680_000
    assert [dataclasses.asdict(t) for t in tokens] == [
        dataclasses.asdict(t) for t in TOKENS
    ]


def test_end_is_recomputed_not_stored(tmp_path: Path) -> None:
    # AlignedToken.__post_init__ derives end from start + duration. Storing it
    # would only create a second source of truth that could disagree.
    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, FP, next_start=0, tokens=TOKENS)
    raw = json.loads(p.read_text())
    assert "end" not in raw["tokens"][0]

    got = read_checkpoint(p, FP)
    assert got is not None
    assert got[1][0].end == TOKENS[0].end


def test_missing_checkpoint_is_not_an_error(tmp_path: Path) -> None:
    assert read_checkpoint(tmp_path / "absent.ckpt", FP) is None


def test_a_truncated_checkpoint_is_discarded(tmp_path: Path) -> None:
    p = tmp_path / "out.json.ckpt"
    p.write_text('{"fingerprint": {"schema": 1,')
    assert read_checkpoint(p, FP) is None


def test_well_formed_json_of_the_wrong_shape_is_discarded(tmp_path: Path) -> None:
    p = tmp_path / "out.json.ckpt"
    p.write_text(json.dumps({"fingerprint": FP.to_dict(), "tokens": "nope"}))
    assert read_checkpoint(p, FP) is None


def test_every_fingerprint_field_invalidates(tmp_path: Path) -> None:
    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, FP, next_start=1_680_000, tokens=TOKENS)

    changed = {
        "schema": SCHEMA + 1,
        "content_id": "1-" + "cd" * 32,
        "total_samples": 1,
        "model_id": "mlx-community/parakeet-tdt-0.6b-v2",
        "chunk_s": 60.0,
        "overlap_s": 5.0,
        # A different engine version, and separately a different engine
        # entirely -- the KEY SET differing is what blocks cross-engine reuse.
        "engine_fields": {"parakeet_version": "0.6.0"},
    }
    assert set(changed) == {f.name for f in dataclasses.fields(Fingerprint) if f.compare}, (
        "a field was added to Fingerprint without a case here"
    )

    for field, value in changed.items():
        other = dataclasses.replace(FP, **{field: value})
        assert read_checkpoint(p, other) is None, f"{field} did not invalidate"


def test_float_values_survive_the_round_trip_bit_for_bit(tmp_path: Path) -> None:
    p = tmp_path / "out.json.ckpt"
    awkward = [
        AlignedToken(
            id=1, text="a", start=0.1 + 0.2, duration=1 / 3,
            confidence=0.9999999999999999,
        ),
        AlignedToken(id=2, text="b", start=4426.987654321, duration=1e-10, confidence=1.0),
    ]
    write_checkpoint(p, FP, next_start=0, tokens=awkward)
    got = read_checkpoint(p, FP)
    assert got is not None
    for a, b in zip(awkward, got[1], strict=True):
        assert struct.pack("<d", a.start) == struct.pack("<d", b.start)
        assert struct.pack("<d", a.duration) == struct.pack("<d", b.duration)
        assert struct.pack("<d", a.confidence) == struct.pack("<d", b.confidence)


def test_the_fingerprint_describes_the_source_media_not_a_temp_wav(tmp_path: Path) -> None:
    """The trap this keying exists to avoid.

    A .mov is extracted to a fresh temp wav on every run, with a new path and a
    new mtime each time. A fingerprint taken from that wav could never match on
    a second run, so resume would silently never fire for exactly the input the
    tool is built for -- while every test on a wav input stayed green.
    """
    source = tmp_path / "recording.mov"
    source.write_bytes(b"pretend this is a screen recording")

    fp = fingerprint(source, total_samples=70_832_448, model_id="m",
                     chunk_s=120.0, overlap_s=15.0,
                     engine_fields={"parakeet_version": "0.5.2"})

    assert fp.content_id == content_id(source)
    assert fp.media == str(source.resolve())

    # Taken twice, with a different extraction in between, it is the same.
    assert fingerprint(source, 70_832_448, "m", 120.0, 15.0,
                       engine_fields={"parakeet_version": "0.5.2"}) == fp


def test_the_media_path_is_a_note_and_not_part_of_the_match(tmp_path: Path) -> None:
    """A renamed, moved or copied recording is the same recording (#118).

    The path is written into the checkpoint so a person can tell which recording
    a stray .ckpt belongs to, and nothing reads it back.
    """
    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, FP, next_start=1_680_000, tokens=TOKENS)
    assert json.loads(p.read_text())["media"] == "/x/meeting.mov"

    elsewhere = dataclasses.replace(FP, media="/y/renamed copy.mov")
    assert elsewhere == FP
    assert read_checkpoint(p, elsewhere) is not None


def test_the_fingerprint_holds_no_path_and_no_mtime(tmp_path: Path) -> None:
    """The two fields that cost a resume on every rename, move and plain `cp` (#118)."""
    source = tmp_path / "recording.mov"
    source.write_bytes(b"x")
    stored = fingerprint(source, 1, "m", 120.0, 15.0, engine_fields={}).to_dict()
    assert not {"media", "media_size", "media_mtime_ns"} & set(stored)


def test_a_re_encoded_source_invalidates(tmp_path: Path) -> None:
    source = tmp_path / "recording.mov"
    source.write_bytes(b"first cut")
    before = fingerprint(source, 100, "m", 120.0, 15.0, engine_fields={})

    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, before, next_start=0, tokens=TOKENS)

    source.write_bytes(b"a different, longer second cut")
    after = fingerprint(source, 100, "m", 120.0, 15.0, engine_fields={})

    assert read_checkpoint(p, after) is None


# --- a checkpoint that is not used says why ----------------------------------
#
# read_checkpoint returns None for "no checkpoint" and for "a checkpoint this run
# cannot use" alike. Until #118 nothing told the two apart, so a rename threw away
# an interrupted hour with no message at all.


def _reasons(path: Path, fp: Fingerprint) -> list[str]:
    reasons: list[str] = []
    assert read_checkpoint(path, fp, on_reject=reasons.append) is None
    return reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("content_id", "1-" + "cd" * 32, "the recording's contents changed (content_id)"),
        ("model_id", "other", "the model changed (model_id)"),
        ("total_samples", 1, "the audio decoded to a different length (total_samples)"),
        ("chunk_s", 60.0, "the chunk length changed (chunk_s)"),
        ("overlap_s", 5.0, "the chunk overlap changed (overlap_s)"),
        ("engine_fields", {"parakeet_version": "0.6.0"},
         "the engine or its version changed (parakeet_version)"),
    ],
)
def test_a_rejected_checkpoint_names_the_field_that_failed(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, FP, next_start=1_680_000, tokens=TOKENS)
    assert _reasons(p, dataclasses.replace(FP, **{field: value})) == [reason]


def test_a_checkpoint_from_another_engine_names_every_engine_key(tmp_path: Path) -> None:
    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, FP, next_start=0, tokens=TOKENS)
    sherpa = dataclasses.replace(
        FP, engine_fields={"sherpa_onnx_version": "1.13.7", "token_times": "measured"}
    )
    # This run's keys first, then the ones only the stored checkpoint has.
    assert _reasons(p, sherpa) == [
        "the engine or its version changed "
        "(sherpa_onnx_version, token_times, parakeet_version)"
    ]


def test_a_checkpoint_in_an_older_format_says_so_and_nothing_else(tmp_path: Path) -> None:
    """Every other key differs too, and listing them would bury the one fact that matters."""
    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, FP, next_start=0, tokens=TOKENS)
    newer = dataclasses.replace(FP, schema=SCHEMA + 1, content_id="1-" + "cd" * 32)
    assert _reasons(p, newer) == [
        f"it was written by another version of dsj, checkpoint schema {SCHEMA} "
        f"where this one reads {SCHEMA + 1} (schema)"
    ]


def test_no_checkpoint_at_all_is_not_a_rejection(tmp_path: Path) -> None:
    assert _reasons(tmp_path / "absent.ckpt", FP) == []


@pytest.mark.parametrize(
    "text",
    ['{"fingerprint": {"schema": 1,', "[]", '{"next_start": 0}'],
    ids=["truncated", "not an object", "no fingerprint"],
)
def test_a_checkpoint_dsj_cannot_read_says_so(tmp_path: Path, text: str) -> None:
    p = tmp_path / "out.json.ckpt"
    p.write_text(text)
    assert _reasons(p, FP) == ["the file is not a checkpoint this dsj can read"]


def test_a_matching_checkpoint_of_the_wrong_shape_says_so(tmp_path: Path) -> None:
    p = tmp_path / "out.json.ckpt"
    p.write_text(json.dumps({"fingerprint": FP.to_dict(), "tokens": "nope"}))
    assert _reasons(p, FP) == ["the file is not a checkpoint this dsj can read"]


def test_a_used_checkpoint_is_not_a_rejection(tmp_path: Path) -> None:
    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, FP, next_start=0, tokens=TOKENS)
    reasons: list[str] = []
    assert read_checkpoint(p, FP, on_reject=reasons.append) is not None
    assert reasons == []


# --- the validated boundary -------------------------------------------------
#
# read_checkpoint parses bytes a PREVIOUS PROCESS wrote. It is the one place in
# dsj that reads a document it did not produce in this run, and until the
# checkpoint was validated it returned whatever the JSON happened to contain.


def _write_raw(path: Path, **overrides: object) -> None:
    """Write a checkpoint straight to disk, bypassing write_checkpoint.

    write_checkpoint cannot produce the shapes below -- that is the point. They
    come from a different writer, an older format, or a partially hand-edited
    file, which is exactly what the validation is for.
    """
    payload: dict[str, object] = {
        "fingerprint": FP.to_dict(),
        "next_start": 44,
        "tokens": [
            {"id": 5, "text": " hello", "start": 1.25, "duration": 0.32, "confidence": 0.91}
        ],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload))


def test_a_string_next_start_is_refused(tmp_path: Path) -> None:
    """The bug this validation exists for.

    Before the model, `payload["next_start"]` was returned unconverted and the
    `except (KeyError, TypeError)` net never fired -- indexing a dict whose
    value is a string raises nothing. read_checkpoint returned ('44', []), and
    the string travelled on to transcribe.py, where `skip_before / rate` raised
    TypeError several frames from the file that produced it.
    """
    p = tmp_path / "out.json.ckpt"
    _write_raw(p, next_start="44")
    assert read_checkpoint(p, FP) is None


def test_a_float_next_start_is_refused(tmp_path: Path) -> None:
    """44.0 is not a sample index, however close it looks to one."""
    p = tmp_path / "out.json.ckpt"
    _write_raw(p, next_start=44.0)
    assert read_checkpoint(p, FP) is None


def test_a_token_missing_a_field_is_refused(tmp_path: Path) -> None:
    """A half-written token means the whole document is untrustworthy."""
    p = tmp_path / "out.json.ckpt"
    _write_raw(p, tokens=[{"id": 5, "text": " hi", "start": 1.25, "duration": 0.32}])
    assert read_checkpoint(p, FP) is None


def test_integer_valued_token_numbers_are_accepted(tmp_path: Path) -> None:
    """Deliberately lax where strictness would DESTROY a resumable run.

    A token whose start/duration/confidence happens to serialise as a bare JSON
    integer is valid data. Under a strict model those are rejected, and a
    rejected checkpoint is a silent full re-transcription presenting as "resume
    just stopped working" -- the exact failure class this validation exists to
    close, reintroduced by the validation itself.

    So the numerics coerce and only next_start is strict. This test is the
    reason that asymmetry is not an oversight.
    """
    p = tmp_path / "out.json.ckpt"
    _write_raw(p, tokens=[{"id": 5, "text": " hi", "start": 0, "duration": 1, "confidence": 1}])

    got = read_checkpoint(p, FP)
    assert got is not None
    next_start, tokens = got
    assert next_start == 44
    assert tokens[0].start == 0.0
    assert tokens[0].duration == 1.0


# --- gaps mutation testing found ---------------------------------------------


def test_the_fingerprint_records_every_field_it_claims_to(tmp_path: Path) -> None:
    """Each field is actually populated, not merely present.

    Six mutants -- schema, total_samples, model_id, engine_fields, chunk_s,
    overlap_s each replaced by None -- survived. `test_every_fingerprint_field
    _invalidates` could not see them: it compares two fingerprints built by the
    SAME function, so a field nulled on both sides still differs wherever it
    differed before. Only an absolute assertion catches a field that stopped
    being read.
    """
    source = tmp_path / "recording.mov"
    source.write_bytes(b"x")

    fp = fingerprint(source, total_samples=70_832_448, model_id="m",
                     chunk_s=120.0, overlap_s=15.0,
                     engine_fields={"parakeet_version": "0.5.2"})

    assert fp.schema == SCHEMA
    assert fp.total_samples == 70_832_448
    assert fp.model_id == "m"
    assert fp.chunk_s == 120.0
    assert fp.overlap_s == 15.0
    # The engine's contribution rides through untouched; the caller supplies
    # it (production sources it from the engine's fingerprint_fields()).
    assert fp.engine_fields == {"parakeet_version": "0.5.2"}


def test_the_checkpoint_is_written_with_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fsync=True at the call site, not just available on the writer.

    Three mutants -- fsync=False, fsync=None, and the argument dropped entirely
    -- survived, and no test could have caught them: whether data reached the
    platter is invisible to a process that then reads its own page cache.
    Asserting on the CALL is the only cheap witness.

    It is worth having. Losing a checkpoint to a power cut costs minutes of GPU
    time, which is the entire reason the argument is there.
    """
    seen: list[bool] = []

    def spy(path: Path, text: str, *, fsync: bool = False) -> None:
        seen.append(fsync)
        path.write_text(text)

    monkeypatch.setattr("dsj.checkpoint.atomic_write_text", spy)
    write_checkpoint(tmp_path / "out.json.ckpt", FP, next_start=44, tokens=TOKENS)

    assert seen == [True]


def test_a_sherpa_checkpoint_from_before_measured_times_does_not_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Old sherpa tokens must not come back labelled as measured (#169).

    Before #77 sherpa guessed each token's duration from the next token's start
    and left its confidence at 1.0, and the checkpoint banks both. Resumed on
    the new code they would be written out as measured `e` and `c`. The marker
    in sherpa's fingerprint_fields() makes those checkpoints stop matching, so
    that run starts over instead.
    """
    import importlib.metadata

    from dsj import sherpa

    def pinned(_name: str) -> str:
        return "1.13.7"

    monkeypatch.setattr(importlib.metadata, "version", pinned)
    now = dataclasses.replace(FP, engine_fields=sherpa.fingerprint_fields())
    before = dataclasses.replace(FP, engine_fields={"sherpa_onnx_version": "1.13.7"})
    p = tmp_path / "out.json.ckpt"
    write_checkpoint(p, before, next_start=0, tokens=TOKENS)

    assert read_checkpoint(p, before) is not None  # the checkpoint itself is sound
    assert read_checkpoint(p, now) is None

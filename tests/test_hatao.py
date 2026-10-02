"""The edit list behind bleeping (#63), on transcripts written here, not on real recordings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from dsj import hatao
from dsj.hatao import Document, InvalidDocument, Item, Paragraph, TranscriptUnusable


def _transcript() -> dict[str, Any]:
    """Two sentences, two speakers, a pause inside the first and a gap between them.

    The pause is the case that matters: " see" ends at 1.4 and " this" starts at
    2.5, so an end taken from the next start would put 1.1 s of silence inside the
    word.
    """
    return {
        "audio": "/elsewhere/rec.mov",
        "engine": "parakeet",
        "model": "m",
        "speakers": ["SPEAKER_00", "SPEAKER_01"],
        "text": "See this. Then that",
        "unclear": [],
        "sentences": [
            {
                "start": 1.0, "end": 3.0, "speaker": 0, "text": " See this.",
                "tokens": [
                    {"t": 1.0, "w": " See", "e": 1.4, "c": 1.0, "charOffset": 0},
                    {"t": 2.5, "w": " this", "e": 2.9, "c": 1.0, "charOffset": 4},
                    {"t": 2.9, "w": ".", "e": 2.9, "c": 1.0, "charOffset": 9},
                ],
            },
            {
                "start": 4.0, "end": 5.0, "speaker": 1, "text": " Then that",
                "tokens": [
                    {"t": 4.0, "w": " Then", "e": 4.3, "c": 1.0, "charOffset": 0},
                    {"t": 4.3, "w": " that", "e": 5.0, "c": 1.0, "charOffset": 5},
                ],
            },
        ],
    }


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    path = tmp_path / "rec.mov"
    path.write_bytes(b"not really a movie, but bytes that must never change" * 100)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_document_plays_the_recording_from_its_start(recording: Path) -> None:
    doc = hatao.from_transcript(_transcript(), recording, duration_s=6.0, language="en")
    assert doc.sources == {"0": str(recording.resolve())}
    spans = [
        (e.source_start, e.source_end, e.text) for e in doc.content if isinstance(e, Item)
    ]
    assert spans == [
        (0.0, 1.0, ""),
        (1.0, 1.4, " See"),
        (1.4, 2.5, ""),
        (2.5, 2.9, " this"),
        (2.9, 2.9, "."),
        (2.9, 4.0, ""),
        (4.0, 4.3, " Then"),
        (4.3, 5.0, " that"),
        (5.0, 6.0, ""),
    ]
    paragraphs = [e for e in doc.content if isinstance(e, Paragraph)]
    assert paragraphs == [Paragraph("SPEAKER_00", "en"), Paragraph("SPEAKER_01", "en")]


def test_a_word_ends_at_its_own_end_never_at_the_next_start(recording: Path) -> None:
    doc = hatao.from_transcript(_transcript(), recording)
    see = next(e for e in doc.content if isinstance(e, Item) and e.text == " See")
    assert see.source_end == pytest.approx(1.4)  # the next word starts at 2.5


def test_a_token_with_no_end_is_refused_rather_than_guessed(recording: Path) -> None:
    payload = _transcript()
    del payload["sentences"][1]["tokens"][1]["e"]
    with pytest.raises(TranscriptUnusable, match=r"sentence 1, token 1 \(at 4.3 s\) has no end"):
        hatao.from_transcript(payload, recording)


def test_tokens_running_backwards_are_refused(recording: Path) -> None:
    payload = _transcript()
    payload["sentences"][1]["tokens"][0]["t"] = 2.0
    with pytest.raises(TranscriptUnusable, match=r"sentence 1, token 0 .* starts before"):
        hatao.from_transcript(payload, recording)


def test_a_word_overlapping_the_next_keeps_its_own_times(recording: Path) -> None:
    """An inferred end (whisper) can run past the next word's start."""
    payload = _transcript()
    payload["sentences"][0]["tokens"][0]["e"] = 2.7
    doc = hatao.from_transcript(payload, recording)
    items = [e for e in doc.content if isinstance(e, Item)]
    assert (items[1].source_start, items[1].source_end) == (1.0, 2.7)
    assert (items[2].source_start, items[2].text) == (2.5, " this")  # no gap invented


def test_no_sentences_is_one_silent_stretch(recording: Path) -> None:
    payload = _transcript()
    payload["sentences"] = []
    doc = hatao.from_transcript(payload, recording, duration_s=3.0)
    assert doc.content == (Paragraph(), Item("0", 0.0, 3.0, ""))


def test_a_bleep_is_data_and_never_touches_the_recording(
    recording: Path, tmp_path: Path
) -> None:
    before = _digest(recording)
    doc = hatao.from_transcript(_transcript(), recording, duration_s=6.0)
    muted = hatao.mute(doc, 2, 3)
    assert [e.muted for e in muted.content if isinstance(e, Item)].count(True) == 1
    edited = hatao.move(hatao.delete(muted, 4, 6), 0, 4, len(muted.content) - 2)
    hatao.save(edited, tmp_path / "doc.json")
    assert _digest(recording) == before


def test_unmuting_gives_back_exactly_the_document_before(recording: Path) -> None:
    doc = hatao.from_transcript(_transcript(), recording)
    assert hatao.mute(hatao.mute(doc, 2, 5), 2, 5, muted=False) == doc


def _words(doc: Document) -> list[str]:
    return [e.text for e in doc.content if isinstance(e, Item) and e.text]


def test_delete_and_move(recording: Path) -> None:
    doc = hatao.from_transcript(_transcript(), recording)
    words = _words
    assert words(hatao.delete(doc, 2, 3)) == [" this", ".", " Then", " that"]
    # The second sentence, paragraph and all, moved to the front.
    second = next(i for i, e in enumerate(doc.content) if e == Paragraph("SPEAKER_01"))
    moved = hatao.move(doc, second, len(doc.content), 0)
    assert words(moved) == [" Then", " that", " See", " this", "."]
    assert hatao.move(moved, 0, len(doc.content) - second, len(doc.content)) == doc
    with pytest.raises(IndexError):
        hatao.move(doc, 1, 4, 2)


def test_a_change_that_breaks_the_list_fails_at_that_change(recording: Path) -> None:
    doc = hatao.from_transcript(_transcript(), recording)
    with pytest.raises(InvalidDocument, match=r"entry 0 .* must open with a paragraph"):
        hatao.delete(doc, 0, 1)


def test_a_document_saves_loads_and_comes_back_identical(
    recording: Path, tmp_path: Path
) -> None:
    doc = hatao.mute(hatao.from_transcript(_transcript(), recording, language="ur"), 2, 3)
    path = tmp_path / "doc.json"
    hatao.save(doc, path)
    assert hatao.load(path) == doc
    saved = json.loads(path.read_text())
    assert (saved["format"], saved["version"]) == ("dsj-edits", 1)
    assert saved["content"][0] == {"kind": "paragraph", "speaker": "SPEAKER_00", "language": "ur"}
    assert saved["content"][2] == {
        "kind": "item", "source": "0", "sourceStart": 1.0, "length": 0.4,
        "text": " See", "muted": True,
    }


def test_language_is_optional_per_paragraph(recording: Path) -> None:
    doc = hatao.from_transcript(_transcript(), recording)
    assert {e.language for e in doc.content if isinstance(e, Paragraph)} == {None}
    assert hatao.loads(hatao.dumps(doc)) == doc


def test_saving_drops_sources_nothing_refers_to(recording: Path, tmp_path: Path) -> None:
    doc = hatao.from_transcript(_transcript(), recording)
    other = Document({**doc.sources, "1": "/elsewhere/other.mov"}, doc.content)
    path = tmp_path / "doc.json"
    hatao.save(other, path)
    assert json.loads(path.read_text())["sources"] == {"0": str(recording.resolve())}
    assert hatao.load(path) == doc


def _file(content: list[Any], **top: Any) -> str:
    return json.dumps(
        {"format": "dsj-edits", "version": 1, "sources": {"0": "/r.mov"}, "content": content}
        | top
    )


PARAGRAPH = {"kind": "paragraph", "speaker": None, "language": None}
ITEM = {"kind": "item", "source": "0", "sourceStart": 1.0, "length": 0.5, "text": " a",
        "muted": False}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ([ITEM], r"entry 0 \(item ' a' at 1 s of source '0'\): the list must open with a"),
        ([PARAGRAPH, ITEM | {"source": "9"}], r"entry 1 .*: no such source"),
        ([PARAGRAPH, ITEM | {"length": -0.1}], r"entry 1 .*: length is -0.1"),
        ([PARAGRAPH, ITEM | {"sourceStart": True}], r"entry 1: `sourceStart` must be a number"),
        ([PARAGRAPH, ITEM | {"muted": "yes"}], r"entry 1: `muted` must be true or false"),
        ([PARAGRAPH, {k: v for k, v in ITEM.items() if k != "text"}],
         r"entry 1: `text` must be a string"),
        ([PARAGRAPH, {"kind": "cut"}], r"entry 1 has kind 'cut'"),
        ([PARAGRAPH | {"language": "Urdu"}], r"entry 0 .*: language 'Urdu' is not a language tag"),
        ([PARAGRAPH, "word"], r"entry 1 is not an object"),
    ],
)
def test_a_malformed_list_is_rejected_naming_the_bad_entry(
    content: list[Any], message: str
) -> None:
    with pytest.raises(InvalidDocument, match=message):
        hatao.loads(_file(content))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (json.dumps({"version": 1}), "not a dsj edit list"),
        (_file([], version=2), "version 2; this dsj reads version 1"),
        (_file([], sources=[]), "needs a `sources` object"),
        (_file([], sources={"0": 3}), "every source must map an id to a path"),
    ],
)
def test_a_file_that_is_not_a_readable_edit_list_says_why(text: str, message: str) -> None:
    with pytest.raises(InvalidDocument, match=message):
        hatao.loads(text)


# --------------------------------------------------------------------------
# Finding the words to bleep (#64)
# --------------------------------------------------------------------------


def _spoken(*sentences: list[str]) -> dict[str, Any]:
    """A transcript of the given tokens, one every second, each half a second long."""
    clock = 0.0
    out: list[dict[str, Any]] = []
    for words in sentences:
        tokens: list[dict[str, Any]] = []
        for w in words:
            tokens.append({"t": clock, "w": w, "e": clock + 0.5, "c": 1.0})
            clock += 1.0
        out.append({"start": tokens[0]["t"], "end": tokens[-1]["e"], "text": "".join(words),
                    "tokens": tokens})
    return {"audio": "/r.mov", "engine": "whisper", "model": "m", "text": "", "unclear": [],
            "sentences": out}


def _found(recording: Path, *sentences: list[str]) -> hatao.Found:
    doc = hatao.from_transcript(_spoken(*sentences), recording)
    return hatao.find(doc, hatao.load_words(hatao.word_lists()))


# Roman Urdu as a recogniser writes it: no fixed spelling, any case, punctuation
# attached, a hyphen inside. Every one is a real variant of a listed word.
ROMAN_URDU_VARIANTS = [
    " bhenchod", " Behenchod", " BENCHOD,", " bhen-chod", " bhanchod", " bhainchod.",
    " madarchod", " Maderchod!", " chutiya", " Chutia", " chootiye", " gandu", " gaandu?",
    " harami", " Haramzada", " haramkhor", " bharwa", " bhadwe", " kameena", " kamine",
    " bhosdike", " lauda", " lawde", " randi", " kanjri", " penchod", " phuddu",
]


def test_every_known_roman_urdu_variant_matches(recording: Path) -> None:
    found = _found(recording, ROMAN_URDU_VARIANTS)
    assert found.count == len(ROMAN_URDU_VARIANTS) == 27
    assert [m.word for m in found.matches] == [w.strip() for w in ROMAN_URDU_VARIANTS]


def test_one_sentence_mixing_languages_and_scripts_matches_word_by_word(
    recording: Path,
) -> None:
    sentence = [" yaar", " this", " is", " fucking", " bakwaas,", " بہنچود", " चूतिया",
                " ਗਾਂਡੂ", " مادرچود"]
    found = _found(recording, sentence)
    assert [m.entry for m in found.matches] == [
        "en:fuck", "ur:behenchod", "hi:chutiya", "pa:gandu", "ur:madarchod",
    ]


def test_arabic_letter_forms_of_an_urdu_word_still_match(recording: Path) -> None:
    # Arabic kaf and yeh for Urdu's kaf and yeh, and a short-vowel mark added.
    assert _found(recording, [" كمينى", " کَمینی"]).count == 2


def test_a_masked_word_is_a_spelling_not_punctuation(recording: Path) -> None:
    # "F" alone is a grade: were the asterisks dropped, "f***" would fold to it.
    found = _found(recording, [" an", " F", " the", " f***", " is", " this", " sh*t"])
    assert [(m.word, m.entry) for m in found.matches] == [("f***", "en:fuck"), ("sh*t", "en:shit")]


def test_a_word_written_in_pieces_matches_and_mutes_all_its_pieces(recording: Path) -> None:
    """Parakeet writes a word as pieces; the second piece has no leading space."""
    doc = hatao.from_transcript(_spoken([" oh", " bhen", "chod", ".", " no"]), recording)
    found = hatao.find(doc, hatao.load_words(hatao.word_lists()))
    assert found.count == 1
    match = found.matches[0]
    assert (match.word, match.source_start, match.source_end) == ("bhenchod.", 1.0, 3.5)
    flagged = hatao.flag(doc, found)
    muted = [e.text for e in flagged.content if isinstance(e, Item) and e.muted]
    assert muted == [" bhen", "", "chod", "", "."]  # the pauses between pieces too
    assert hatao.mute(flagged, match.start, match.stop, muted=False) == doc


def test_a_term_that_matches_nothing_is_a_zero_count_not_an_empty_success(
    recording: Path,
) -> None:
    found = _found(recording, [" that", " is", " what", " I", " said"])
    assert found.count == 0
    assert found.words_searched == 5
    assert [p.name for p in found.lists] == ["en.toml", "ur.toml", "hi.toml", "pa.toml"]


def test_ordinary_words_near_a_listed_spelling_do_not_match(recording: Path) -> None:
    # Each is one letter from a listed spelling (twat, chut, lun, gand), which is why
    # matching is exact rather than by edit distance.
    assert _found(recording, [" that", " chhut", " run", " gande", " kutta"]).count == 0


def test_the_user_list_adds_words_and_lives_outside_the_package(recording: Path) -> None:
    user = hatao.user_words_path()
    assert Path(hatao.__file__).parent not in user.parents
    assert _found(recording, [" lovely", " weather"]).count == 0
    user.write_text('[[entry]]\nname = "weather"\nroman = ["weather", "wether"]\n')
    found = _found(recording, [" lovely", " Weather."])
    assert [(m.word, m.entry) for m in found.matches] == [("Weather.", "user:weather")]
    assert found.lists[-1] == user


def test_the_user_list_sits_beside_the_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worked out twice, since hatao imports nothing from dsj.ui; held equal here."""
    from dsj.ui.store import library_path

    monkeypatch.delenv("DSJ_WORDS")
    monkeypatch.delenv("DSJ_LIBRARY")
    assert hatao.user_words_path() == library_path().with_name("words.toml")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[entry]]\nname = "x"\nspellings = ["x"]\n', r"has keys \['spellings'\]"),
        ('[[entry]]\nroman = ["x"]\n', "has no `name`"),
        ('[[entry]]\nname = "x"\n', "needs at least one spelling"),
        ('[[entry]]\nname = "x"\nroman = ["..."]\n', "is all punctuation"),
        ("[[entry]\n", "is not valid TOML"),
    ],
)
def test_a_broken_user_list_is_named(text: str, message: str) -> None:
    user = hatao.user_words_path()
    user.write_text(text)
    with pytest.raises(hatao.WordListError, match=message):
        hatao.load_words(hatao.word_lists())


def test_every_shipped_list_loads_and_ships_inside_the_package() -> None:
    package = Path(hatao.__file__).parent
    for path in hatao.word_lists():
        assert path.parent == package / "words"
        assert hatao.load_words([path]).spellings, f"{path.name} has no spellings"

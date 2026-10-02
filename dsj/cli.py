"""The `dsj` command -- one Typer app, six verbs.

    dsj suno   recording.mov -o transcript.json    # listen
    dsj dekho  recording.mov -t transcript.json    # look
    dsj dikhao recording.mov 431.5 -o frame.jpg    # show me
    dsj likho  transcript.json -o captions.srt     # write
    dsj parho  recording.mov captions.vtt -o transcript.json    # read
    dsj ui                                         # the app, in a browser

Urdu imperatives, and they are not decoration: the first three name the things
the tool does in the order it does them. Suno gives you what was said, dekho
gives you when the picture changed, dikhao gives you the picture itself. Jaano
-- know -- is what you get from all three, which is why it is the command.
Likho writes what suno heard out for the tools that are not dsj, and parho reads
a transcript those tools made back in, in place of suno. `ui` is plain English
because it is not a step in that sequence: it is the window over all of them.

This file owns ALL argument parsing for the project. `dsj.suno.main`
and `dsj.dekho.main` are thin shims onto the commands below, so
`python -m dsj.suno` keeps working and there is exactly one definition
of every flag rather than one per entry point.

WHY standalone_mode, AND WHY THE SystemExit CATCH. Typer's other calling
convention, `app(args=..., standalone_mode=False)`, returns the command's value
directly and looks like the obvious fit for `main(argv) -> int`. It is a trap
here for two measured reasons:

  * Typer 0.27 VENDORS its own Click at `typer._click`. Its `UsageError` is not
    the `click.exceptions.UsageError` class, so the obvious `except
    click.exceptions.UsageError` never fires and a bad flag escapes as an
    unhandled NoSuchOption traceback. Catching it properly means importing from
    a private module.
  * standalone_mode=False also skips Click's error rendering, so every usage
    message would have to be reimplemented here.

standalone_mode=True renders errors the way every other Click program does and
raises SystemExit with the right code; catching that gives back the int. Checked
against all six cases that matter: success 0, --help 0, unknown flag 2, no args
2, a caller's own exception PROPAGATES (which the resume tests depend on), and
KeyboardInterrupt becomes 130.
"""

from __future__ import annotations

__all__ = ["app", "main", "run"]

import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from types import FrameType
from typing import Annotated

import typer

from dsj.asr import EngineUnavailable

# Module level, not lazy. These are DEFAULTS, and a lazily-resolved default
# cannot appear in --help: the first version of this file used 0 as a "not
# given" sentinel and Typer duly advertised `[default: 0]` for a budget whose
# real default is 150. Measured cost of the import: ~90ms, inside the noise of
# `dsj --help` at 120-200ms. The heavy workers below stay lazy.
from dsj.dekho import DEFAULT_BUDGET, DEFAULT_DELTA, DEFAULT_FPS, DEFAULT_MIN_GAP_S
from dsj.media import FFmpegNotFound
from dsj.suno import DEFAULT_MODEL, DEFAULT_WHISPER_MODEL, ENGINES, RunRefused, Terminated

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    # Tracebacks are the project's failure surface -- media.py raises
    # MediaError with the ffmpeg log and a command to reproduce it by hand.
    # Typer's pretty exceptions reformat that into a box and truncate the
    # frames, so a real diagnosis gets prettier and less useful.
    pretty_exceptions_enable=False,
    help="Make a long screen recording answerable.",
)


def _show_version(value: bool) -> None:
    """Print `dsj <version>` and stop, before any verb is parsed.

    Read from dsj.__version__ and never typed here: pyproject.toml holds the
    other copy, a test holds the two equal, and a third would be the one that
    drifts.
    """
    if value:
        from dsj import __version__

        print(f"dsj {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    _version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True,
            help="print the version and exit",
        ),
    ] = False,
) -> None:
    """Make a long screen recording answerable.

    The callback exists only to carry --version (#50), which is how a document
    or a bug report gets pinned to the build it was written against. Its
    docstring repeats the Typer help= above because, with a callback present,
    Typer reads the group's help from here.
    """


def _stderr_logger(name: str) -> None:
    """Attach the one stderr handler a CLI is allowed to install.

    A bare handler rather than basicConfig: basicConfig is a no-op once the root
    logger has handlers, which is exactly the case under pytest, and a gate that
    silently does nothing is the failure this project exists to remove.
    """
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# The failures of `dsj suno` that are its caller's to fix, each already a
# sentence carrying its remedy: a mistake in the arguments (RunRefused), and an
# engine or ffmpeg that is not installed. Listed, never `Exception`: everything
# else is a bug in dsj and keeps its traceback (#200).
_CALLERS_TO_FIX: tuple[type[Exception], ...] = (RunRefused, EngineUnavailable, FFmpegNotFound)

# EX_TEMPFAIL from sysexits.h, "try again later": the run did not fail, it
# never started, and the same command will work once the other run is over.
EXIT_ALREADY_RUNNING = 75


def _raise_terminated(_signum: int, _frame: FrameType | None) -> None:
    """SIGTERM becomes Terminated where the run is, so `kill` stops it as Ctrl-C does (#143).

    The default goes back first, so a second `kill` ends the process at once
    instead of interrupting the `interrupted` document transcribe() is writing.
    """
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    raise Terminated


def _record_in_library(out: Path, engine: str, language: str | None) -> None:
    """Add a finished run to the library, so `dsj ui` lists it (#57, #156).

    The owner's answer, on 2 Oct 2026, to #127's open adoption question: a
    transcript made in the terminal shows up in the app. Here and not in
    transcribe(), because the app's own jobs call transcribe() and record their
    run themselves (dsj/ui/jobs.py); in both places, every app job would be
    recorded twice.

    Every failure is caught, unlike _CALLERS_TO_FIX: the transcript is already
    written and is the truth, and the library is only an index over it, so a
    library that cannot be opened or written costs the app's list one row and
    never the run. The warning names the library's file and the error's class.
    The store is plain sqlite3 (dsj/ui/__init__.py), so this needs no `ui` extra.
    """
    from dsj.ui.store import Library, library_path

    try:
        with Library.open() as library:
            library.record_run(out, engine=engine, language=language)
    except Exception as exc:
        print(
            f"transcript not added to the library at {library_path()}, so `dsj ui` will "
            f"not list it: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


@app.command("suno")
def suno(
    media: Annotated[Path, typer.Argument(help="video or audio file; a .mov is the normal case")],
    out: Annotated[Path, typer.Option("--out", "-o", help="where the transcript JSON goes")],
    model: Annotated[
        str | None,
        typer.Option("--model", help=f"the ASR model (default: {DEFAULT_MODEL} per --engine)"),
    ] = None,
    engine: Annotated[
        str, typer.Option("--engine", help=f"ASR backend: {' | '.join(ENGINES)}")
    ] = "parakeet",
    language: Annotated[
        str | None,
        typer.Option("--language", help="whisper only: ISO code, e.g. ur. Detected if omitted"),
    ] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", help="whisper only: seeds the decoder; biases spelling+script"),
    ] = None,
    roman_urdu: Annotated[
        bool,
        typer.Option(
            "--roman-urdu",
            help="whisper only: Urdu, written in Latin. Sets --language ur and a measured --prompt",
        ),
    ] = False,
    status: Annotated[
        Path | None, typer.Option("--status", help="JSON heartbeat file for detached runs")
    ] = None,
    no_resume: Annotated[
        bool, typer.Option("--no-resume", help="ignore any checkpoint and start over")
    ] = False,
    no_diarize: Annotated[
        bool, typer.Option("--no-diarize", help="skip speaker labelling")
    ] = False,
    require_diarize: Annotated[
        bool,
        typer.Option("--require-diarize", help="fail rather than degrade if labelling cannot run"),
    ] = False,
) -> int:
    """Listen: transcribe media to a timestamped index."""
    from dsj import runlock
    from dsj.suno import Progress, clock, render_bar
    from dsj.suno import roman_urdu as roman_urdu_settings
    from dsj.suno import transcribe as run_transcribe

    _stderr_logger("dsj.suno")

    # \r only rewrites the line on a terminal; when piped, print one line per
    # chunk instead so a captured log stays readable rather than becoming one
    # enormous line of control characters.
    tty = sys.stderr.isatty()
    last_state = ""
    last_total = 0.0

    def show(p: Progress, state: str) -> None:
        # A phase change ends the rewritten line, so the finished extraction bar
        # stays on screen instead of being overwritten by transcription's 0%.
        nonlocal last_state, last_total
        if tty and last_state and state != last_state:
            print(file=sys.stderr)
        last_state = state
        last_total = p.audio_total_s
        print(render_bar(p, state), end="\r" if tty else "\n", file=sys.stderr, flush=True)

    # --roman-urdu is sugar over the flags under it, defined once in dsj/suno.py
    # so that a run started from `dsj ui` gets exactly what this one does (#113).
    anchor_s = None
    if roman_urdu:
        engine, language, prompt, anchor_s = roman_urdu_settings(engine, language, prompt)

    # Resolved here, not in transcribe(): this file owns every default in the
    # project, and a default that lives in two places is a default that will
    # disagree with `--help` eventually.
    model = model or (DEFAULT_WHISPER_MODEL if engine == "whisper" else DEFAULT_MODEL)

    # Only where SIGTERM still has its default action, and only on the main
    # thread, the one place signal.signal is allowed. A caller that ignored
    # SIGTERM on purpose, or installed its own handler, keeps it. SIGINT needs
    # nothing: Python already raises KeyboardInterrupt for it, unless the
    # process started with SIGINT ignored, which is what a `&` job in a shell
    # without job control gets, and that choice is the caller's to keep too.
    sigterm_installed = (
        threading.current_thread() is threading.main_thread()
        and signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
    )
    if sigterm_installed:
        signal.signal(signal.SIGTERM, _raise_terminated)

    # Before anything is loaded or written, and before --status is touched: a
    # refused run that wrote "failed" into a status path it shares with the run
    # it is refusing would overwrite that run's heartbeat (#136).
    try:
        held = runlock.acquire(
            {
                "pid": os.getpid(),
                "out": str(out.absolute()),
                "status": str(status.absolute()) if status else None,
                "media": str(media.absolute()),
            }
        )
    except runlock.AlreadyRunning as busy:
        if sigterm_installed:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        print(f"dsj: {busy}", file=sys.stderr)
        raise typer.Exit(EXIT_ALREADY_RUNNING) from None

    started = time.monotonic()
    try:
        result = run_transcribe(
            media,
            out,
            model,
            status_path=status,
            on_progress=show,
            resume=not no_resume,
            diarize=not no_diarize,
            require_diarize=require_diarize,
            engine=engine,
            language=language,
            prompt=prompt,
            anchor_s=anchor_s,
        )
    except Terminated:
        # transcribe() has already written `interrupted` to --status (#103), as
        # it writes `failed` for an exception, which passes through untouched.
        # 128 + 15, what a shell reports for a process SIGTERM ended, so
        # `wait` and anything already reading 143 see what they saw before.
        # A Ctrl-C passes through too, and Typer turns it into exit 130.
        raise SystemExit(143) from None
    except _CALLERS_TO_FIX as exc:
        # One line, not a traceback (#200). transcribe() has already written
        # `failed` to --status. Anything not listed is a bug in dsj, and keeps
        # its traceback.
        print(f"dsj: {exc}", file=sys.stderr)
        raise typer.Exit(1) from None
    finally:
        os.close(held)
        if sigterm_installed:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
    if tty:
        print(file=sys.stderr)
    elapsed = time.monotonic() - started
    _record_in_library(out, engine, language)
    # The done frame's total, read off the frame rather than recomputed, so
    # this line and the status file cannot name two lengths for one run (#52).
    # It used to be rebuilt from the last sentence: `done: 0:00 audio` for
    # four minutes of audio with no speech in it.
    total = last_total
    # A count, not a rate. `total / elapsed` would credit a resumed run with
    # work a previous process paid for -- an hour finished in two minutes reads
    # as 30x. Guarded on the key because a degraded run has no speakers.
    speakers = f" · {len(result['speakers'])} speakers" if "speakers" in result else ""
    print(f"done: {clock(total)} audio in {clock(elapsed)}{speakers} -> {out}", file=sys.stderr)
    return 0


@app.command("dekho")
def dekho(
    media: Annotated[Path, typer.Argument(help="the video the transcript indexes")],
    transcript: Annotated[
        Path, typer.Option("--transcript", "-t", help="transcript to add marks to")
    ],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="where to write; defaults to overwriting --transcript"),
    ] = None,
    fps: Annotated[
        float, typer.Option(help="frames sampled per second of video")
    ] = DEFAULT_FPS,
    delta: Annotated[
        int, typer.Option(help="grey levels a tile must move to count")
    ] = DEFAULT_DELTA,
    budget: Annotated[int, typer.Option(help="how many marks to keep")] = DEFAULT_BUDGET,
    min_gap: Annotated[
        float, typer.Option("--min-gap", help="seconds two marks must be apart")
    ] = DEFAULT_MIN_GAP_S,
) -> int:
    """Look: mark the moments the picture changed most."""
    from dsj.dekho import logger, mark_video

    _stderr_logger("dsj.dekho")
    tty = sys.stderr.isatty()
    started = time.monotonic()

    def show(done_s: float) -> None:
        elapsed = time.monotonic() - started
        speed = done_s / elapsed if elapsed > 0 else 0.0
        print(
            f"scanning {done_s:7.0f}s of video  {speed:4.1f}x",
            end="\r" if tty else "\n",
            file=sys.stderr,
            flush=True,
        )

    result = mark_video(
        media,
        transcript,
        out or transcript,
        fps=fps,
        delta=delta,
        budget=budget,
        min_gap_s=min_gap,
        on_progress=show,
    )
    if tty:
        print(file=sys.stderr)
    logger.info(
        "%d marks over %d sampled frames in %.0fs",
        len(result["marks"]),
        result["marks_meta"]["frames_sampled"],
        time.monotonic() - started,
    )
    return 0


@app.command("dikhao")
def dikhao(
    video: Annotated[Path, typer.Argument(help="the recording to seek into")],
    seconds: Annotated[float, typer.Argument(help="offset into the recording")],
    out: Annotated[Path, typer.Option("--out", "-o", help=".jpg is what a vision model wants")],
    width: Annotated[
        int,
        typer.Option(
            help="scale to this width, aspect preserved; 0 keeps the source resolution"
        ),
        # 1500 is a measured ceiling, not a taste: a full 2940px frame is
        # ~776 KB as a JPEG, over what most vision APIs accept, and legibility
        # stopped improving well below it -- 700px to 1600px moved recall by one
        # string in fifteen (docs/vlm-legibility.md).
    ] = 1500,
) -> int:
    """Show me: write the frame at a given second to an image file."""
    from dsj.media import extract_frame

    dest = extract_frame(video, seconds, out, width=width or None)
    # The path alone on stdout, and nothing else. The caller is usually a
    # program, and a path on stdout composes:
    #     open "$(dsj frame rec.mov 431.5 -o /tmp/f.jpg)"
    print(dest)
    return 0


@app.command("likho")
def likho(
    transcript: Annotated[Path, typer.Argument(help="a transcript suno wrote")],
    out: Annotated[
        Path, typer.Option("--out", "-o", help="where the file goes: .srt, .vtt or .txt")
    ],
    fmt: Annotated[
        str | None,
        typer.Option("--format", help="srt, vtt or txt; read from the --out suffix if omitted"),
    ] = None,
) -> int:
    """Write: export a transcript as SRT, WebVTT or plain text."""
    from dsj.atomic import atomic_write_text
    from dsj.likho import EXPORTERS

    chosen = (fmt or out.suffix.removeprefix(".")).lower()
    if chosen not in EXPORTERS:
        # A usage error, before anything is read or written: a guessed format is
        # a file of the wrong kind under the name the caller asked for.
        raise typer.BadParameter(f"must be srt, vtt or txt, not {chosen!r}", param_hint="--format")
    atomic_write_text(out, EXPORTERS[chosen](json.loads(transcript.read_text())))
    return 0


@app.command("parho")
def parho(
    media: Annotated[Path, typer.Argument(help="the recording the transcript indexes")],
    source: Annotated[
        Path, typer.Argument(help="an SRT, WebVTT or dsj JSON transcript; the content decides")
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="where the transcript JSON goes")],
) -> int:
    """Read: import an SRT, WebVTT or JSON transcript instead of running ASR."""
    from dsj.atomic import atomic_write_text
    from dsj.parho import parse

    # The recording is never opened, only named, but a transcript naming one
    # that is not there is an index into nothing; dekho would fail on it later
    # and further from the typo.
    if not media.exists():
        raise FileNotFoundError(media)
    # utf-8-sig: caption files from Windows tools often open with a BOM. The
    # recording by its absolute path, as `dsj suno` names it (#201).
    payload = parse(source.read_text(encoding="utf-8-sig"), str(media.resolve()))
    atomic_write_text(out, json.dumps(payload))
    return 0


@app.command("ui")
def ui(
    print_url: Annotated[
        bool,
        typer.Option("--print-url", help="print the URL and serve, without opening a browser"),
    ] = False,
) -> int:
    """Open the app: every recording dsj knows, in a browser window."""
    from dsj.ui import require_extra

    # Inside the command, not at the top of this file: fastapi costs every
    # `dsj --help` and every `dsj suno` its import time otherwise, and most
    # installs never open the app.
    require_extra()
    from dsj.ui.server import serve

    serve(open_browser=not print_url)
    return 0


def run(argv: list[str]) -> int:
    """Invoke the app on `argv` and return an exit code instead of exiting.

    The one place SystemExit is converted back into a value, so every
    `main(argv) -> int` in the package can share it. Exceptions other than
    SystemExit propagate untouched -- a failing transcription must still reach
    the caller as itself, not as an exit code.
    """
    try:
        app(args=argv, standalone_mode=True)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 0
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `dsj` console script.

    Returns:
        A process exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    # `dsj help` as well as `dsj --help`. Typer offers no `help` command
    # and the bare word is what people type.
    if args and args[0] == "help":
        args = ["--help"]
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

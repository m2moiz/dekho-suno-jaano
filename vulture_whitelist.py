"""Deliberate exceptions for vulture (the orphan gate).

Almost everything here is read by a framework through reflection, so no
reachable call site exists for vulture to find. Two findings from the same
sweep were real and were deleted instead of listed (an unused tmp_path_factory
in conftest's chunked_audio_path, an unused capsys in test_resume_cli) -- this
file is only for names whose "caller" is pytest, pydantic, or a signature
contract. The one exception is marked where it sits: a name with a real call
site that the orphan gate cannot see, because it scans only the files a branch
changed.
"""

from typing import Any

whitelist: Any = None

# pydantic reads ConfigDict off the class attribute; nothing else may.
whitelist.model_config  # dsj/checkpoint.py -- _CheckpointDoc

# pytest collects these by NAME: the collection hook, module-level marks, and
# every fixture. Their call sites live inside pytest, not this repo.
whitelist.pytest_collection_modifyitems  # tests/conftest.py
whitelist.pytestmark  # tests/test_install_gate.py, tests/test_resume_cli.py
whitelist.fake_parakeet  # tests/conftest.py
whitelist.fake_media  # tests/conftest.py
whitelist.frozen_clock  # tests/conftest.py
whitelist.already_extracted_media  # tests/conftest.py
whitelist.no_real_diarizer  # tests/conftest.py
whitelist.private_suno_lock  # tests/conftest.py
whitelist.private_words  # tests/conftest.py
whitelist.private_library  # tests/conftest.py, autouse
# A session fixture, injected by name into the slow tests that load a model.
whitelist.model_id  # tests/conftest.py
# Signature fidelity for conftest's stand-ins: each restates the parameters of
# the function it replaces (parakeet_mlx's load_audio, media.needs_conversion,
# media.loudness), and the caller passes them, so the body ignoring one is the
# point of a stub. Seen only when a branch changes conftest.
whitelist.rate  # tests/conftest.py
whitelist.stream  # tests/conftest.py
whitelist.frame_s  # tests/conftest.py
whitelist.end_what_the_test_started  # tests/test_run_guards.py, autouse
whitelist.no_stub_outlives_the_module  # tests/test_run_guards.py, autouse
# A session fixture, injected by name into tests/test_chunking.py,
# tests/test_diarize.py, tests/test_resume_cli.py and tests/test_resume_gate.py.
whitelist.chunked_audio_path  # tests/conftest.py

# Protocol signature fidelity: _Transcribes restates BaseParakeet.transcribe,
# and the parameter names must match upstream's keyword API exactly.
whitelist.chunk_duration  # tests/test_chunking.py
whitelist.overlap_duration  # tests/test_chunking.py

# typer registers these by decorator, `@app.command("suno")` and friends, so
# the only caller is typer's own dispatch. `dsj --help` lists all three, which
# is the check that they are wired: a genuinely dead command would not appear.
whitelist.suno  # dsj/cli.py
whitelist.dekho  # dsj/cli.py
whitelist.dikhao  # dsj/cli.py
whitelist.hatao  # dsj/cli.py
whitelist.likho  # dsj/cli.py
whitelist.parho  # dsj/cli.py
whitelist.ui  # dsj/cli.py
# The same for the group callback, `@app.callback()`, which exists to carry
# --version. `dsj --version` printing the version is the check that it is wired.
whitelist.root  # dsj/cli.py

# autouse fixture: pytest instantiates it for every test in the module without
# any test naming it, so there is no call site here either.
whitelist.no_real_senko  # tests/test_diarize.py

# Signature fidelity again, this time for a test double. fake_load_audio
# restates mlx_whisper.audio.load_audio's `(file, sr=16000, from_stdin=False)`
# exactly. The body ignores all three because it returns zeros, but the
# parameters are load-bearing: dsj/whisper.py:208 calls it as
# `_load_audio(str(audio), sr=SAMPLE_RATE)`, so a stub missing `sr` raises
# TypeError instead of standing in.
whitelist.file  # tests/test_whisper.py
whitelist.sr  # tests/test_whisper.py
whitelist.from_stdin  # tests/test_whisper.py

# The exception the docstring names. Every ChunkEngine declares this and the
# chunk loop reads it, `if end - start < engine.min_chunk_samples:` at
# dsj/chunking.py:87. The orphan gate scans only the files a branch changed,
# and chunking.py is rarely one of them, so a branch that touches an engine
# sees its declaration as unused.
whitelist.min_chunk_samples  # dsj/asr.py, dsj/parakeet.py, dsj/sherpa.py

# The same blind spot, for a test double. _SherpaRecognizer and _SherpaStream
# stand in for sherpa_onnx's, and dsj/sherpa.py:146-148 calls all three. A
# branch that changes tests/test_suno.py and not dsj/sherpa.py scans the fakes
# without their caller and reports them unused.
whitelist.create_stream  # tests/test_suno.py
whitelist.accept_waveform  # tests/test_suno.py
whitelist.decode_stream  # tests/test_suno.py

# The same blind spot, for conftest's FakeModel. dsj/parakeet.py:132-166 reads
# `model.preprocessor_config` and calls `model.generate(mel, ...)`, so a branch
# that changes tests/conftest.py and not dsj/parakeet.py scans the fake without
# its caller and reports both unused.
whitelist.preprocessor_config  # tests/conftest.py
whitelist.generate  # tests/conftest.py

# Read by reflection too: Fingerprint.to_dict() serializes every field through
# dataclasses.asdict, which is how `schema` reaches every checkpoint and every
# comparison of one. Nothing reads it as an attribute, so a branch that changes
# dsj/checkpoint.py sees it as unused.
whitelist.schema  # dsj/checkpoint.py -- Fingerprint

# uvicorn calls it by name, `dsj.ui.server:dev_app --factory`, from the
# justfile's ui-dev recipe, which vulture does not read.
whitelist.dev_app  # dsj/ui/server.py

# Set by the idle watchdog, read inside uvicorn's own serve loop, which vulture
# does not scan: uvicorn.Server polls `should_exit` and shuts down when it is True.
whitelist.should_exit  # dsj/ui/server.py -- _watch

# A FastAPI route: the @router.get decorator registers it, and FastAPI calls it
# for each request. Its other routes' names happen to be used elsewhere too.
whitelist.waveform  # dsj/ui/routes/media.py
whitelist.import_recording  # dsj/ui/routes/recording.py, the same: @router.post registers it
# Read by reflection: the engines route turns each EngineChoice into the
# Engine model through dataclasses.asdict, and pydantic fills Engine's
# fields from it; FastAPI then serializes them. Nothing reads either as an
# attribute (#113).
whitelist.default_model  # dsj/ui/jobs.py EngineChoice, dsj/ui/schemas.py Engine
whitelist.read_edits  # dsj/ui/routes/marks.py, the same: @router.get registers it

# The page's half of the wire format (#155): pydantic reads every field of these
# models when FastAPI serializes or parses a request, and `just api` generates
# ui/src/api/schema.d.ts from them, where the page reads each one. Nothing in
# Python reads them as attributes, so a branch that changes dsj/ui/schemas.py
# sees them as unused. Each is read on the page or by dsj/ui/jobs.py.
whitelist.finished_at  # dsj/ui/schemas.py Transcript
whitelist.diarized  # dsj/ui/schemas.py Transcript
whitelist.speaker_count  # dsj/ui/schemas.py Transcript
whitelist.mark_count  # dsj/ui/schemas.py Transcript
whitelist.size_bytes  # dsj/ui/schemas.py Recording
whitelist.audio_codec  # dsj/ui/schemas.py Recording
whitelist.first_seen  # dsj/ui/schemas.py Recording
whitelist.unreadable  # dsj/ui/schemas.py Recording
whitelist.reason  # dsj/ui/schemas.py Engine
whitelist.diarize  # dsj/ui/schemas.py TranscribeRequest, read by dsj/ui/jobs.py
whitelist.start_over  # dsj/ui/schemas.py TranscribeRequest, read by dsj/ui/jobs.py
whitelist.reports_progress  # dsj/ui/schemas.py Job
whitelist.started_at  # dsj/ui/schemas.py Job
whitelist.fraction  # dsj/ui/schemas.py Job
whitelist.audio_done_s  # dsj/ui/schemas.py Job
whitelist.elapsed_s  # dsj/ui/schemas.py Job
whitelist.eta_s  # dsj/ui/schemas.py Job
whitelist.stalled_s  # dsj/ui/schemas.py Job
whitelist.error  # dsj/ui/schemas.py Job
whitelist.notes  # dsj/ui/schemas.py Job

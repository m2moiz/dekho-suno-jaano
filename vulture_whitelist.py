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
whitelist.likho  # dsj/cli.py
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

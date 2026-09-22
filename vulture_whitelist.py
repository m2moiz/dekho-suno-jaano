"""Deliberate exceptions for vulture (the orphan gate).

Everything here is read by a framework through reflection, so no reachable
call site exists for vulture to find. Two findings from the same sweep were
real and were deleted instead of listed (an unused tmp_path_factory in
conftest's chunked_audio_path, an unused capsys in test_resume_cli) -- this
file is only for names whose "caller" is pytest, pydantic, or a signature
contract.
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

# autouse fixture: pytest instantiates it for every test in the module without
# any test naming it, so there is no call site here either.
whitelist.no_real_senko  # tests/test_diarize.py

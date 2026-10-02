"""The API description the frontend's types are generated from (#155).

`just api-fresh`, inside `just check`, holds ui/src/api/schema.d.ts to this
description. That only protects the page if the description says something: a
route whose reply is an untyped dict comes out as `{[key: string]: unknown}`,
and then reading a field that does not exist is not a tsc error at all.
"""

from __future__ import annotations

from dsj.ui.server import dev_app

RECORDING_REF = "#/components/schemas/Recording"


def test_the_recordings_reply_is_a_list_of_typed_recordings() -> None:
    spec = dev_app().openapi()
    reply = spec["paths"]["/api/recordings"]["get"]["responses"]["200"]
    schema = reply["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"] == {"$ref": RECORDING_REF}


def test_every_field_of_a_recording_is_required_so_the_page_never_guesses() -> None:
    """A field the server always sends is required in TypeScript too.

    An optional one (`x?: T`) makes every read of it check for a value that is
    never missing. Nullable is fine, and is how "unknown" is said.
    """
    schemas = dev_app().openapi()["components"]["schemas"]
    for name in ("Recording", "Transcript"):
        schema = schemas[name]
        assert sorted(schema["required"]) == sorted(schema["properties"]), name

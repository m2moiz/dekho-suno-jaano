"""Review mode's routes (#248): read and save a transcript's review, and write its answer key.

The work is in dsj/ui/review.py; this file only turns requests into its calls.
"""

from __future__ import annotations

__all__ = ["router"]

from fastapi import APIRouter

from dsj.ui import review
from dsj.ui.routes.marks import transcript_number
from dsj.ui.schemas import ReferenceRequest, ReferenceWritten, Review, ReviewDocument

router = APIRouter(prefix="/api")


@router.get("/transcripts/{transcript_id}/review")
def read_review(transcript_id: str) -> Review:
    """The transcript's review, or none, and the sha of the transcript as it is now."""
    document, digest = review.read_review(transcript_number(transcript_id))
    return Review(document=document, transcript_sha=digest)


@router.put("/transcripts/{transcript_id}/review")
def save_review(transcript_id: str, document: ReviewDocument) -> ReviewDocument:
    """Save the page's review in place of the last one, or refuse it whole, naming the segment."""
    return review.save_review(transcript_number(transcript_id), document)


@router.post("/transcripts/{transcript_id}/reference")
def write_reference(transcript_id: str, request: ReferenceRequest) -> ReferenceWritten:
    """Write the answer key beside the transcript; refused while unchecked, unless allow_partial."""
    return review.reference(transcript_number(transcript_id), allow_partial=request.allow_partial)

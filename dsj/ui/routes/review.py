"""Review mode's routes (#248): read and save a transcript's review, and write its answer key.

The work is in dsj/ui/review.py; this file only turns requests into its calls.
"""

from __future__ import annotations

__all__ = ["router"]

from fastapi import APIRouter

from dsj.ui import review
from dsj.ui.routes.marks import transcript_number
from dsj.ui.schemas import (
    ReferenceRequest,
    ReferenceWritten,
    Review,
    ReviewDocument,
    ReviewPatch,
    ReviewSaved,
)

router = APIRouter(prefix="/api")


@router.get("/transcripts/{transcript_id}/review")
def read_review(transcript_id: str) -> Review:
    """The transcript's review, or none, and the sha of the transcript as it is now."""
    document, digest = review.read_review(transcript_number(transcript_id))
    sha = None if document is None else review.review_sha(document)
    return Review(document=document, transcript_sha=digest, review_sha=sha)


@router.put("/transcripts/{transcript_id}/review")
def save_review(transcript_id: str, document: ReviewDocument) -> ReviewSaved:
    """Save the page's review in place of the last one, or refuse it whole, naming the segment.

    The answer is its sha, not the review sent back: the page already has it (#251).
    """
    saved = review.save_review(transcript_number(transcript_id), document)
    return ReviewSaved(review_sha=review.review_sha(saved), updated_at=saved.updated_at)


@router.patch("/transcripts/{transcript_id}/review")
def patch_review(transcript_id: str, change: ReviewPatch) -> ReviewSaved:
    """Save one change to the review, made against the review `review_sha` names (#251)."""
    saved = review.patch_review(
        transcript_number(transcript_id),
        sha=change.transcript_sha,
        against=change.review_sha,
        start=change.start,
        delete=change.delete,
        insert=change.insert,
        corrections=change.corrections,
        review_pass=change.review_pass,
        cursor_s=change.cursor_s,
    )
    return ReviewSaved(review_sha=review.review_sha(saved), updated_at=saved.updated_at)


@router.post("/transcripts/{transcript_id}/reference")
def write_reference(transcript_id: str, request: ReferenceRequest) -> ReferenceWritten:
    """Write the answer key beside the transcript; refused while unchecked, unless allow_partial."""
    return review.reference(transcript_number(transcript_id), allow_partial=request.allow_partial)

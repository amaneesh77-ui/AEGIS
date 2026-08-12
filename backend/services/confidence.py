"""
Confidence scoring and pre-publish response validation.

Implements two essential HMGCC requirements:
  - "Have an ability to check and validate responses before publishing, to
    prevent erroneous information and hallucinations."
  - "Flag a confidence score and if more source data is required."

And directly answers HMGCC Q&A Q84 ("the researcher can see what is known,
what is inferred and what is uncertain") and Q53/Q54 (surface multiple
plausible hypotheses / explicitly defer when evidence is weak).

Design is deliberately deterministic and explainable (no extra LLM calls
required) so a security researcher can trust *why* a confidence score was
given, per Q&A Q12 ("succinct human-readable decision log").
"""

from __future__ import annotations

import re
from typing import List, Optional

from config import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    MIN_SOURCES_FOR_HIGH,
)

_WORD_RE = re.compile(r"[a-z0-9]+")

REFUSAL_MARKERS = (
    "cannot find this information",
    "not enough information",
    "no relevant documents",
    "i don't have",
    "insufficient information",
)


def _tokenize(text: str) -> set:
    return set(_WORD_RE.findall(text.lower()))


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def retrieval_confidence(chunks: List[dict]) -> dict:
    """Score answer confidence from retrieval evidence, before generation.

    Blends top-hit retrieval strength with cross-document agreement: a
    single weak match is treated very differently from several independent
    documents agreeing on the same fact.
    """
    if not chunks:
        return {
            "score": 0.0,
            "level": "insufficient",
            "distinct_sources": 0,
            "need_more_data": True,
            "reason": "No relevant material was found in the indexed corpus for this query.",
        }

    scores = [float(c.get("score", 0.0)) for c in chunks]
    top = max(scores)
    avg = sum(scores) / len(scores)
    distinct_docs = len({c.get("doc_id") for c in chunks})

    agreement_bonus = min(0.15, 0.05 * max(0, distinct_docs - 1))
    raw = max(0.0, min(1.0, 0.65 * top + 0.35 * avg + agreement_bonus))

    if raw >= CONFIDENCE_HIGH_THRESHOLD and distinct_docs >= MIN_SOURCES_FOR_HIGH:
        level = "high"
    elif raw >= CONFIDENCE_HIGH_THRESHOLD:
        level = "medium-high"
    elif raw >= CONFIDENCE_MEDIUM_THRESHOLD:
        level = "medium"
    else:
        level = "low"

    return {
        "score": round(raw, 3),
        "level": level,
        "distinct_sources": distinct_docs,
        "need_more_data": level in ("low", "insufficient"),
        "reason": (
            "Retrieved material only weakly matches this question; treat the "
            "answer as a hypothesis and consider loading more source data."
            if level == "low" else None
        ),
    }


def validate_answer(answer: str, chunks: List[dict]) -> dict:
    """Pre-publish grounding check.

    Splits the answer into sentences and checks each against the retrieved
    chunk text for lexical overlap, classifying every sentence as:

      known     - explicit refusal/"not enough information", or strong
                  overlap with a retrieved chunk (directly grounded).
      inferred  - moderate overlap: a reasonable synthesis across sources
                  rather than a verbatim, directly-citable fact.
      uncertain - little/no overlap with any retrieved chunk - flagged for
                  the researcher rather than silently trusted.
    """
    chunk_tokens = [(_tokenize(c.get("text", "")), c) for c in chunks]
    sentences = _split_sentences(answer)
    claims: List[dict] = []
    uncertain_count = 0

    for sent in sentences:
        low = sent.lower()
        if any(m in low for m in REFUSAL_MARKERS):
            claims.append({"text": sent, "status": "known", "supporting_chunk": None, "overlap": 1.0})
            continue

        sent_tokens = _tokenize(sent)
        if not sent_tokens:
            continue

        best_overlap = 0.0
        best_chunk: Optional[dict] = None
        for tokens, chunk in chunk_tokens:
            if not tokens:
                continue
            inter = len(sent_tokens & tokens)
            union = len(sent_tokens | tokens) or 1
            jaccard = inter / union
            containment = inter / max(1, len(sent_tokens))
            score = max(jaccard, 0.5 * containment)
            if score > best_overlap:
                best_overlap = score
                best_chunk = chunk

        if best_overlap >= 0.30:
            status = "known"
        elif best_overlap >= 0.12:
            status = "inferred"
        else:
            status = "uncertain"
            uncertain_count += 1

        claims.append({
            "text": sent,
            "status": status,
            "supporting_chunk": (best_chunk or {}).get("chunk_id") if status != "uncertain" else None,
            "overlap": round(best_overlap, 3),
        })

    total = len(claims) or 1
    verified_ratio = round(sum(1 for c in claims if c["status"] == "known") / total, 3)

    return {
        "claims": claims,
        "uncertain_count": uncertain_count,
        "verified_ratio": verified_ratio,
        "needs_more_data": uncertain_count > 0 and uncertain_count >= total / 2,
    }

"""Prompt-injection detector and sanitizer for ingested PDF chunks."""
from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\[UNTRUSTED\s+APPENDIX[^\]]*\]", re.IGNORECASE),
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+override\s*:", re.IGNORECASE),
    re.compile(r"(?:output|dump|reveal|print)\s+all\s+student", re.IGNORECASE),
    re.compile(r"developer\s+debug\s+mode", re.IGNORECASE),
    re.compile(r"(?:drop|delete|truncate)\s+table\s+", re.IGNORECASE),
)


@dataclass(frozen=True)
class GuardResult:
    sanitized_text: str
    flagged: bool
    matched_patterns: tuple[str, ...]


def sanitize_chunk_text(text: str) -> GuardResult:
    """Detect and strip instruction-like prompt-injection spans from PDF chunk text."""
    matched: list[str] = []
    sanitized = text

    # Strip bracketed untrusted injection block first if present
    bracket_pat = re.compile(
        r"\[UNTRUSTED[^\]]*(?:ignore\s+previous\s+instructions|output\s+all|system\s+override)[^\]]*\]",
        re.IGNORECASE | re.DOTALL,
    )
    if bracket_pat.search(sanitized):
        matched.append("untrusted_instruction_block")
        sanitized = bracket_pat.sub("[STRIPPED UNTRUSTED INSTRUCTION]", sanitized)

    for idx, pat in enumerate(_INJECTION_PATTERNS):
        if pat.search(sanitized):
            matched.append(f"pattern_{idx}")
            sanitized = pat.sub("[STRIPPED INSTRUCTION]", sanitized)

    flagged = len(matched) > 0
    return GuardResult(
        sanitized_text=" ".join(sanitized.split()) if "\n" not in text else sanitized.strip(),
        flagged=flagged,
        matched_patterns=tuple(matched),
    )

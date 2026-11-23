"""Phase 6 Code Verifier + optional LLM Claim Check on Policy Claims."""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from src.config import AppConfig
from src.llm.client import llm
from src.synthesis.models import (
    Claim,
    SourceRegistry,
    VerificationIssue,
    VerificationResult,
)

ClaimCheckerFn = Callable[[Claim, dict[str, Any]], dict[str, Any]]

LLM_CLAIM_CHECK_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "supported": {"type": "BOOLEAN"},
        "contradiction": {"type": "BOOLEAN"},
        "reason": {"type": "STRING"},
    },
    "required": ["supported", "contradiction", "reason"],
}

_FLAT_ELIGIBILITY_RE = re.compile(
    r"\b(?:you(?:'re|\s+are)\s+(?:100%\s+|fully\s+|definitely\s+)?eligible|100%\s+eligible)\b",
    flags=re.IGNORECASE,
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "is", "are", "for", "to", "of", "in", "on", "with",
    "by", "from", "that", "this", "must", "be", "has", "have", "not", "all", "per",
}


def _norm_num(val: Any) -> float | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    cleaned = re.sub(r"[\$,%\s]", "", s)
    if re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _norm_str(val: Any) -> str:
    return re.sub(r"\s+", " ", str(val).strip().lower())


def _scalar_matches(claim_val: Any, row_val: Any) -> bool:
    if row_val is None:
        return False
    # Boolean check
    if isinstance(claim_val, bool) or isinstance(row_val, bool):
        cb = claim_val if isinstance(claim_val, bool) else _norm_str(claim_val) in ("true", "1", "yes")
        rb = row_val if isinstance(row_val, bool) else _norm_str(row_val) in ("true", "1", "yes")
        if _norm_str(claim_val) in ("true", "false", "1", "0", "yes", "no") and _norm_str(row_val) in ("true", "false", "1", "0", "yes", "no"):
            return cb == rb

    cn = _norm_num(claim_val)
    rn = _norm_num(row_val)
    if cn is not None and rn is not None:
        return abs(cn - rn) <= 0.015

    cs = _norm_str(claim_val)
    rs = _norm_str(row_val)
    if not cs:
        return False
    if cs == rs or cs in rs:
        return True
    # Normalize currency punctuation (e.g. "$5,500" vs "5500")
    cs_clean = re.sub(r"[\$,]", "", cs)
    rs_clean = re.sub(r"[\$,]", "", rs)
    return bool(cs_clean and (cs_clean == rs_clean or (len(cs_clean) >= 3 and cs_clean in rs_clean)))


def _entity_matches_sql_row(entity: str, row: dict[str, Any]) -> bool:
    """Verify claim.entity belongs to THIS specific SQL row when row carries an explicit ID/name."""
    ent_low = _norm_str(entity)
    if not ent_low or ent_low in ("aggregate", "summary", "query", "all"):
        return True
    id_keys = ("grant_id", "student_id", "course_id", "faculty_name", "waiver_id", "ledger_id", "lab_id", "full_name")
    present_ids = [_norm_str(row[k]) for k in id_keys if k in row and row[k] is not None]
    if not present_ids:
        return True
    # Match if entity equals or substring-matches any primary identifier/name on this row
    return any(ent_low == pid or ent_low in pid or pid in ent_low for pid in present_ids)


def _passage_blob(passage: dict[str, Any]) -> str:
    parts = [str(passage.get("text") or "")]
    tbl = passage.get("structured_table_json")
    if isinstance(tbl, dict):
        headers = tbl.get("headers") or []
        parts.append(" ".join(str(h) for h in headers))
        for r in tbl.get("rows") or []:
            if isinstance(r, dict):
                parts.append(" ".join(f"{k} {v}" for k, v in r.items()))
    return " ".join(parts)


def _value_grounded_in_passage(claim_val: Any, passage: dict[str, Any]) -> tuple[bool, str]:
    blob = _passage_blob(passage)
    blob_low = _norm_str(blob)
    blob_clean = re.sub(r"[\$,]", "", blob_low)

    val_low = _norm_str(claim_val)
    val_clean = re.sub(r"[\$,]", "", val_low)
    if not val_low:
        return False, "Empty claim value."

    if val_low in blob_low or (val_clean and val_clean in blob_clean):
        return True, "Exact substring match in own passage."

    # Check all numbers / dollar amounts in claim appear in THIS passage
    claim_nums = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", str(claim_val))
    blob_nums = {n.replace(",", "") for n in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", blob)}
    for num in claim_nums:
        clean_n = num.replace(",", "")
        if clean_n not in blob_nums and clean_n.rstrip(".0") not in {b.rstrip(".0") for b in blob_nums}:
            return False, f"Numeric token '{num}' in claim not found in own passage {passage.get('chunk_id')}."

    # Check content-word lexical overlap strictly inside THIS passage
    words = [w for w in re.findall(r"[a-z0-9_]+", val_low) if len(w) >= 3 and w not in _STOPWORDS]
    if not words:
        return False, "No verifiable content tokens in policy claim."
    blob_words = set(re.findall(r"[a-z0-9_]+", blob_clean))
    hits = sum(1 for w in words if w in blob_words)
    ratio = hits / len(words)
    if ratio >= 0.70:
        return True, f"Content tokens grounded ({hits}/{len(words)}) in own passage."
    return False, f"Only {hits}/{len(words)} claim tokens matched own passage {passage.get('chunk_id')}."


def _offline_llm_claim_check(claim: Claim, passage: dict[str, Any]) -> dict[str, Any]:
    grounded, reason = _value_grounded_in_passage(claim.value, passage)
    # Also detect obvious direct negation conflicts (e.g. claim says "stackable" when passage says "not stackable")
    val_low = _norm_str(claim.value)
    blob_low = _norm_str(_passage_blob(passage))
    contradiction = False
    if "stackable" in val_low and "not stackable" not in val_low and "no longer stackable" not in val_low:
        if "not stackable" in blob_low or "no longer stackable" in blob_low:
            contradiction = True
            grounded = False
            reason = "Claim states stackable, which contradicts 'not stackable' in passage."
    return {
        "supported": grounded and not contradiction,
        "contradiction": contradiction,
        "reason": reason,
    }


def check_rendered_text_safety(rendered_text: str) -> list[VerificationIssue]:
    """Ensure rendered text never outputs a flat 'you're eligible' verdict."""
    issues: list[VerificationIssue] = []
    # Strip quoted negative disclaimers if any, check remaining text
    if _FLAT_ELIGIBILITY_RE.search(rendered_text):
        issues.append(
            VerificationIssue(
                claim_index=-1,
                entity="answer_format",
                field="eligibility_verdict",
                source_id="rendered_markdown",
                check_type="flat_eligibility_phrase",
                message="Rendered answer contains prohibited flat eligibility verdict ('you're eligible' / 'you are eligible').",
            )
        )
    return issues


def verify_claims(
    claims: list[Claim],
    registry: SourceRegistry,
    *,
    cfg: AppConfig | None = None,
    use_llm_claim_check: bool | None = None,
    claim_checker_fn: ClaimCheckerFn | None = None,
) -> VerificationResult:
    """Verify every claim strictly against its OWN source_id row/passage and optional LLM claim check."""
    active_cfg = cfg or AppConfig.load("config.yaml")
    run_llm_check = active_cfg.flags.use_llm_claim_check if use_llm_claim_check is None else bool(use_llm_claim_check)

    issues: list[VerificationIssue] = []
    policy_claims: list[tuple[int, Claim, dict[str, Any]]] = []

    for idx, claim in enumerate(claims):
        sid = str(claim.source_id or "").strip()
        if not sid:
            issues.append(
                VerificationIssue(
                    claim_index=idx,
                    entity=claim.entity,
                    field=claim.field,
                    source_id="",
                    check_type="source_missing",
                    message="Claim has empty source_id.",
                )
            )
            continue

        if sid.startswith("sql:"):
            row = registry.sql_rows.get(sid)
            if row is None:
                issues.append(
                    VerificationIssue(
                        claim_index=idx,
                        entity=claim.entity,
                        field=claim.field,
                        source_id=sid,
                        check_type="source_missing",
                        message=f"SQL source '{sid}' was not found in retrieved SQL rows.",
                    )
                )
                continue

            if not _entity_matches_sql_row(claim.entity, row):
                issues.append(
                    VerificationIssue(
                        claim_index=idx,
                        entity=claim.entity,
                        field=claim.field,
                        source_id=sid,
                        check_type="value_mismatch",
                        message=f"Claim entity '{claim.entity}' does not match own SQL row '{sid}'.",
                    )
                )
                continue

            # If field matches a column on THIS row, verify strictly against THAT column on THAT row
            field_norm = _norm_str(claim.field)
            matched = False
            if field_norm in row:
                matched = _scalar_matches(claim.value, row[field_norm])
            else:
                # Derived/aliased field: value must still exist inside THIS exact row dict
                matched = any(_scalar_matches(claim.value, v) for v in row.values())

            if not matched:
                issues.append(
                    VerificationIssue(
                        claim_index=idx,
                        entity=claim.entity,
                        field=claim.field,
                        source_id=sid,
                        check_type="value_mismatch",
                        message=(
                            f"Value {claim.value!r} for '{claim.entity}.{claim.field}' "
                            f"did not match its own SQL row '{sid}'."
                        ),
                    )
                )

        elif sid.startswith("doc:"):
            passage = registry.doc_passages.get(sid)
            if passage is None:
                issues.append(
                    VerificationIssue(
                        claim_index=idx,
                        entity=claim.entity,
                        field=claim.field,
                        source_id=sid,
                        check_type="source_missing",
                        message=f"Document source '{sid}' was not found in retrieved passages.",
                    )
                )
                continue

            if claim.claim_type == "policy":
                cit = str(claim.citation or "").strip()
                if not cit:
                    issues.append(
                        VerificationIssue(
                            claim_index=idx,
                            entity=claim.entity,
                            field=claim.field,
                            source_id=sid,
                            check_type="missing_citation",
                            message=f"Policy claim '{claim.entity}.{claim.field}' is missing required citation.",
                        )
                    )
                    continue
                doc_id = str(passage.get("doc_id") or "")
                if doc_id and doc_id not in cit:
                    issues.append(
                        VerificationIssue(
                            claim_index=idx,
                            entity=claim.entity,
                            field=claim.field,
                            source_id=sid,
                            check_type="missing_citation",
                            message=f"Policy citation '{cit}' does not reference own passage doc_id '{doc_id}'.",
                        )
                    )
                    continue

            grounded, reason = _value_grounded_in_passage(claim.value, passage)
            if not grounded:
                issues.append(
                    VerificationIssue(
                        claim_index=idx,
                        entity=claim.entity,
                        field=claim.field,
                        source_id=sid,
                        check_type="value_mismatch",
                        message=reason,
                    )
                )
                continue

            if claim.claim_type == "policy":
                policy_claims.append((idx, claim, passage))

        else:
            issues.append(
                VerificationIssue(
                    claim_index=idx,
                    entity=claim.entity,
                    field=claim.field,
                    source_id=sid,
                    check_type="source_missing",
                    message=f"Unrecognized source_id prefix '{sid}'. Expected 'sql:...' or 'doc:...'.",
                )
            )

    # Optional LLM Claim Check on grounded policy claims
    llm_backend = "disabled"
    llm_ran = False
    if run_llm_check and policy_claims:
        llm_ran = True
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if claim_checker_fn is not None:
            llm_backend = "custom_claim_checker"
        elif api_key and api_key != "MY_GEMINI_API_KEY":
            llm_backend = f"llm_fast:{active_cfg.raw.get('models', {}).get('default_fast_model', 'gemini-2.5-flash')}"
        else:
            llm_backend = "deterministic_entailment_fallback"

        for idx, claim, passage in policy_claims:
            if claim_checker_fn is not None:
                verdict = claim_checker_fn(claim, passage)
            elif api_key and api_key != "MY_GEMINI_API_KEY":
                try:
                    msgs = [
                        {
                            "role": "system",
                            "content": (
                                "Verify strictly whether the Policy Claim is directly supported by the Source Passage "
                                "without contradiction. Return JSON {supported, contradiction, reason}."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Policy Claim: entity={claim.entity}, field={claim.field}, value={claim.value}\n"
                                f"Citation: {claim.citation}\n\n"
                                f"Source Passage ({passage.get('citation')}):\n{_passage_blob(passage)}"
                            ),
                        },
                    ]
                    res = llm("fast", msgs, schema=LLM_CLAIM_CHECK_SCHEMA, cfg=active_cfg)
                    verdict = res.parsed if isinstance(res.parsed, dict) else _offline_llm_claim_check(claim, passage)
                except Exception:
                    verdict = _offline_llm_claim_check(claim, passage)
            else:
                verdict = _offline_llm_claim_check(claim, passage)

            supported = bool(verdict.get("supported", False))
            contradiction = bool(verdict.get("contradiction", False))
            if not supported or contradiction:
                issues.append(
                    VerificationIssue(
                        claim_index=idx,
                        entity=claim.entity,
                        field=claim.field,
                        source_id=claim.source_id,
                        check_type="llm_claim_check",
                        message=str(verdict.get("reason") or "Policy claim failed LLM entailment check."),
                    )
                )

    return VerificationResult(
        passed=len(issues) == 0,
        issues=issues,
        llm_check_ran=llm_ran,
        llm_check_backend=llm_backend,
        checked_claims_count=len(claims),
        policy_claims_count=len(policy_claims),
    )

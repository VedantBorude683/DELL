from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
API_URL = "http://127.0.0.1:8000"
PERSONA = "STU-1001"

TEST_CASES = [
    {"question": "What is Maya Lin's cumulative GPA?", "route": "sql"},
    {"question": "Which open grants may Maya Lin qualify for based on the database?", "route": "sql"},
    {"question": "What is the submission window for the Turing Undergraduate Research Fellowship?", "route": "vector"},
    {"question": "What deadline does the database list for GR-CS-01, and what date appears in the 2026 handbook?", "route": "hybrid"},
    {"question": "What courses is Maya Lin taking in Fall 2026?", "route": "sql"},
    {"question": "How much does Maya Lin still owe?", "route": "sql"},
    {"question": "Can internal Alderwood research stipends be stacked?", "route": "vector"},
    {"question": "What lab or safety clearance is required for the Maxwell Hardware Prototyping Grant?", "route": "hybrid"},
    {"question": "Was the Summer 2026 Heritage Innovation Grant expired by November 23, 2026?", "route": "hybrid"},
    {"question": "What is the weather in London today?", "route": "out_of_scope"},
]


def call_chat(question: str) -> tuple[dict | None, str | None, float]:
    payload = json.dumps({
        "query": question,
        "persona_student_id": PERSONA,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.loads(response.read().decode("utf-8"))
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return result, None, elapsed
    except urllib.error.HTTPError as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        body = exc.read().decode("utf-8", "replace")
        return None, f"HTTP {exc.code}: {body}", elapsed
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return None, f"{type(exc).__name__}: {exc}", elapsed


def main() -> None:
    records: list[dict] = []
    for case in TEST_CASES:
        result, error, elapsed = call_chat(case["question"])
        if error:
            records.append({
                "question": case["question"],
                "expected_route": case["route"],
                "status": "error",
                "error": error,
                "latency_ms": elapsed,
            })
            continue

        plan = result.get("plan") or {}
        sql = result.get("sql_result") or {}
        docs = result.get("doc_result") or {}
        synthesis = result.get("synthesis") or {}
        passages = docs.get("passages") or []
        records.append({
            "question": case["question"],
            "expected_route": case["route"],
            "actual_route": plan.get("route"),
            "route_correct": plan.get("route") == case["route"],
            "execution_mode": plan.get("execution_mode"),
            "decision_path": plan.get("decision_path"),
            "sql": sql.get("sql"),
            "sql_row_count": len(sql.get("rows") or []),
            "sql_rows": sql.get("rows") or [],
            "pdf_passage_count": len(passages),
            "pdf_citations": [p.get("citation") for p in passages],
            "pdf_passages": passages,
            "answer": synthesis.get("answer_markdown"),
            "verification_passed": synthesis.get("verification", {}).get("passed"),
            "latency_ms": elapsed,
            "token_summary": result.get("token_summary") or {},
            "status": "success",
        })

    successes = [r for r in records if r["status"] == "success"]
    route_correct = sum(bool(r["route_correct"]) for r in successes)
    verification_passed = sum(bool(r["verification_passed"]) for r in successes)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "api_url": API_URL,
        "persona_student_id": PERSONA,
        "test_count": len(TEST_CASES),
        "success_count": len(successes),
        "routing_accuracy": round(route_correct / len(successes), 4) if successes else 0.0,
        "verification_pass_rate": round(verification_passed / len(successes), 4) if successes else 0.0,
        "results": records,
    }
    out = ROOT / "eval" / "live_10_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

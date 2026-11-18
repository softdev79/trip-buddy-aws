"""Post-deploy evals: ask the live API golden questions and grade the answers.

    python evals/run_evals.py http://<alb-dns>          (or http://localhost:8000)
    python evals/run_evals.py http://<alb-dns> --report docs/evidence/evals-live.json

Each case checks the answer AND the trajectory (which tools ran, over which protocol), because a
right number reached without calling compute_trip_cost is a lucky guess, not a working agent.
Exits non-zero below PASS_THRESHOLD so the deploy pipeline can fail on a quality regression.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

PASS_THRESHOLD = 0.8
CASES = json.loads((Path(__file__).parent / "golden.json").read_text(encoding="utf-8"))


def normalise(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", text).lower()   # 11,800 -> 11800


def grade(case: dict, data: dict) -> list[str]:
    failures = []
    reply = normalise(data["reply"])
    for needle in case.get("expect_in_reply", []):
        if needle.lower() not in reply:
            failures.append(f"reply missing '{needle}'")
    if any_of := case.get("expect_any_in_reply"):
        if not any(n.lower() in reply for n in any_of):
            failures.append(f"reply has none of {any_of}")
    used = {(s["tool"], s["via"]) for s in data["steps"]}
    for tool, via in case.get("expect_tools", []):
        if (tool, via) not in used:
            failures.append(f"tool {tool} via {via} not called")
    if any(via == "blocked" for _, via in used):
        failures.append("model tried to call an unknown tool")
    for hit in case.get("expect_rag", []):
        if hit not in data["rag_hits"]:
            failures.append(f"rag did not retrieve '{hit}'")
    return failures


def main(base_url: str, report: str | None = None) -> int:
    passed, latencies, results = 0, [], []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=120) as client:
        for case in CASES:
            t0 = time.perf_counter()
            r = client.post("/api/chat", json={"message": case["question"]})
            latencies.append(time.perf_counter() - t0)
            if r.status_code != 200:
                print(f"FAIL {case['id']}: HTTP {r.status_code} {r.text[:200]}")
                results.append({"id": case["id"], "passed": False, "failures": [f"HTTP {r.status_code}"]})
                continue
            failures = grade(case, r.json())
            results.append({"id": case["id"], "question": case["question"], "passed": not failures,
                            "failures": failures, "latency_s": round(latencies[-1], 2),
                            "steps": r.json()["steps"], "rag_hits": r.json()["rag_hits"],
                            "reply": r.json()["reply"]})
            if failures:
                print(f"FAIL {case['id']}: {'; '.join(failures)}\n     reply: {r.json()['reply'][:300]}")
            else:
                passed += 1
                print(f"PASS {case['id']}  ({latencies[-1]:.1f}s)")
    score = passed / len(CASES)
    latencies.sort()
    print(f"\n{passed}/{len(CASES)} passed ({score:.0%}); "
          f"p50 latency {latencies[len(latencies) // 2]:.1f}s, max {latencies[-1]:.1f}s")
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(json.dumps({
            "target": "live AWS deployment" if "elb.amazonaws.com" in base_url else base_url,
            "run_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "passed": passed, "total": len(CASES), "score": score,
            "p50_latency_s": round(latencies[len(latencies) // 2], 2), "max_latency_s": round(latencies[-1], 2),
            "cases": results}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"report written to {report}")
    return 0 if score >= PASS_THRESHOLD else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    report = None
    if "--report" in args:
        i = args.index("--report")
        report = args[i + 1]
        del args[i:i + 2]
    sys.exit(main(args[0] if args else "http://localhost:8000", report))

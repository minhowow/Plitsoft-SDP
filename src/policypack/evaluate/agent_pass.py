"""에이전트 검토 단계 — 정적 판정이 낸 경고를 후보 단위로 묶어 에이전트형 판정기에게 묻고, 인용 관문을 거쳐 반영한다.

정적 판정(evaluate)이 끝난 뒤에 돈다. `--agent` 를 주지 않으면 돌지 않으므로 `--judge none` 의 판정은 그대로다.

반영 규칙(방향성 신뢰 — 약한 근거는 경고를 올릴 수만 있다)
  충족·해당 없음   인용 가운데 하나 이상이 관문(evidence.is_grounded)을 통과해야 경고를 푼다. 인용은 여러 파일에
                   걸칠 수 있고, 저장소 밖 파일·주석·낱말 하나·지어낸 줄은 떨어진다. 통과한 인용이 없으면 경고가 남는다.
  미충족           경고를 남기고, 불확실이었으면 검토 필요로 올린다. 인용을 요구하지 않는다(경고를 올리는 쪽).
  모름·실패        정적 판정 그대로 둔다.
푼 경고는 지우지 않고 기록(`agent.units[].findings`)에 남긴다. 관문은 인용이 코드에 있는지만 보고 의무와
관련 있는지는 보지 못하므로, 사람이 볼 수 있어야 한다.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from policypack.evidence import classify, is_grounded
from policypack.index import build_index
from policypack.index.units import candidate_units
from policypack.judge.agent import AgentJudge, AgentQuestion
from policypack.report.outcome import Outcome
from policypack.report.paths import rel


def gate(root: Path, citations: list[dict]) -> list[dict]:
    """인용마다 관문 결과. [{file, line, text, ok, why}]"""
    root = root.resolve()
    out = []
    for c in citations:
        f, text = str(c.get("file", "")), str(c.get("text", ""))
        rec = {"file": f, "line": c.get("line"), "text": text, "ok": False, "why": ""}
        p = (root / f.lstrip("/")).resolve()
        if p != root and root not in p.parents:
            rec["why"] = "outside-repo"
        elif not p.is_file():
            rec["why"] = "no-such-file"
        else:
            code = p.read_text(encoding="utf-8", errors="replace")
            rec["ok"] = is_grounded(text, code)
            rec["why"] = "grounded" if rec["ok"] else classify(text, code).value
        out.append(rec)
    return out


def run_agent_pass(
    result,
    root: Path,
    pack,
    duties: dict[str, dict],
    judge: AgentJudge,
    files: list[Path],
    max_units: int | None = None,
) -> dict:
    """`result`(EvalResult)의 findings 를 고친다. 반환값은 보고서 `run.agent` 에 실을 기록."""
    root = root.resolve()
    index = build_index(root, files)
    by_rel: dict[tuple[str, str], list] = {}
    plain = []
    for f in result.findings:
        r = rel(f.file, root)
        by_rel.setdefault((f.policy, r), []).append(f)
        plain.append({"policy": f.policy, "rule": f.rule, "file": r, "line": f.line, "outcome": f.outcome.value})
    units = candidate_units(plain, index)
    policies = {p.id: p for p in pack.policies}
    records, cleared_ids, changed = [], set(), {}
    asked = units if max_units is None else units[:max_units]
    for u in asked:
        pol = policies.get(u.policy)
        q = AgentQuestion(
            policy=u.policy,
            title=pol.title if pol else u.policy,
            duties=tuple(duties[d] for d in (pol.duties if pol else []) if d in duties),
            entry=u.entry,
            lines=tuple(u.lines),
            related=tuple(u.related),
            ask_developer=(pol.ask_developer or "") if pol else "",
        )
        ans = judge.ask(q, root)
        checked = gate(root, ans.citations)
        grounded = any(c["ok"] for c in checked)
        if ans.failure:
            action = "kept"
        elif ans.verdict in ("compliant", "not-applicable"):
            action = "cleared" if grounded else "kept-ungrounded"
        elif ans.verdict == "not-compliant":
            action = "confirmed"
        else:
            action = "kept"
        mine = by_rel.get((u.policy, u.entry), [])
        note = {"verdict": ans.verdict, "action": action, "reason": ans.reason, "citations": checked}
        for f in mine:
            if action == "cleared":
                cleared_ids.add(id(f))
            else:
                outcome = Outcome.NEEDS_REVIEW if action == "confirmed" else f.outcome
                changed[id(f)] = replace(
                    f, outcome=outcome, agent=note, trace=[*f.trace, f"agent: {ans.verdict} → {action}"]
                )
        records.append(
            {
                **u.as_dict(),
                **note,
                "failure": ans.failure,
                "tool_calls": ans.tool_calls,
                "usage": ans.usage,
                "findings": [{"rule": f.rule, "line": f.line, "outcome": f.outcome.value} for f in mine],
            }
        )
    result.findings = [changed.get(id(f), f) for f in result.findings if id(f) not in cleared_ids]
    actions: dict[str, int] = {}
    for r in records:
        actions[r["action"]] = actions.get(r["action"], 0) + 1
    rejected = sum(1 for r in records for c in r["citations"] if not c["ok"])
    total = sum(len(r["citations"]) for r in records)
    return {
        "judge": judge.id,
        "units": len(units),
        "asked": len(asked),
        "actions": actions,
        "model_calls": judge.calls,
        "usage": judge.usage,
        "citations": total,
        "citations_rejected": rejected,
        "index": index.summary(),
        "records": records,
    }

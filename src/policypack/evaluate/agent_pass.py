"""에이전트 검토 단계 — 정적 경고를 (저장소, 정책)마다 묶어 에이전트형 판정기에게 묻고, 인용 관문을 거쳐 반영한다.

두 방식이 있다.

review (M4, `--agent`)
  정적 판정(evaluate)이 끝난 뒤에 돈다. 경고를 후보 단위(진입 파일 + 함께 볼 파일)로 만들고, 같은 정책의 단위들을
  CHUNK 개씩 한 대화로 묻는다. 의무는 서비스에 붙어서, 단위를 따로 물으면 같은 저장소·같은 정책인데 한 단위는 다른
  파일의 이행 근거를 찾아 풀고 다른 단위는 못 찾아 미충족이라 했다(11/3 실측). 묶음이 여럿이면 앞 묶음에서 관문을
  통과한 이행 근거를 다음 묶음에 알려 준다(다음 묶음은 직접 읽어 확인해야 한다).

independent (M3, `--agent-mode independent`)
  정적 경고 없이, 정책마다 판정기가 저장소에서 의무가 걸리는 처리를 스스로 찾고 판단한다. 정적 판정의 경고는 쓰지
  않는다. 판정기가 '미충족'·'모름'이라 한 곳이 경고가 된다(진입 파일이 저장소에 없으면 버린다).

반영 규칙(review, 방향성 신뢰 — 약한 근거는 경고를 올릴 수만 있다)
  충족·해당 없음   그 진입 파일에 대한 인용 가운데 하나 이상이 관문(evidence.is_grounded)을 통과해야 경고를 푼다.
                   충족의 인용은 여러 파일에 걸칠 수 있다. 해당 없음은 진입 파일에 대한 말이라 진입 파일의 줄만 받는다.
                   저장소 밖 파일·주석·낱말 하나·지어낸 줄은 떨어진다.
  미충족           경고를 남기고, 불확실이었으면 검토 필요로 올린다. 인용을 요구하지 않는다(경고를 올리는 쪽).
  모름·실패·답 없음 정적 판정 그대로 둔다.
푼 경고는 지우지 않고 기록(`records[].findings`)에 남긴다. 관문은 인용이 코드에 있는지만 보고 의무와 관련 있는지는
보지 못하므로, 사람이 볼 수 있어야 한다. 무엇을 읽어 밖으로 보냈는지(`sent`)도 남긴다.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from policypack.evidence import classify, is_grounded
from policypack.index import build_index
from policypack.index.units import candidate_units
from policypack.judge.agent import AgentAnswer, AgentJudge, AgentQuestion, Entry
from policypack.report.outcome import Finding, Outcome
from policypack.report.paths import rel

CHUNK = 6
"""한 대화에 묻는 진입 파일 수. 많으면 도구 예산이 모자라 뒤쪽 파일을 덜 본다."""
CARRY = 5
"""다음 묶음에 넘길 이행 근거 수."""


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


def _question(pol, duties: dict[str, dict], policy_id: str, **kw) -> AgentQuestion:
    return AgentQuestion(
        policy=policy_id,
        title=pol.title if pol else policy_id,
        duties=tuple(duties[d] for d in (pol.duties if pol else []) if d in duties),
        ask_developer=(pol.ask_developer or "") if pol else "",
        **kw,
    )


def _sent(ans: AgentAnswer) -> dict:
    return {"read": ans.read_files, "searches": ans.searches, "masked": ans.masked}


def _summary(judge: AgentJudge, records: list[dict], questions: list[dict], extra: dict) -> dict:
    """한 단계의 기록. 호출 수와 토큰은 이 단계의 질문들에서 센다(판정기 전체 누계가 아니다)."""
    actions: dict[str, int] = {}
    for r in records:
        actions[r["action"]] = actions.get(r["action"], 0) + 1
    usage: dict[str, int] = {}
    for q in questions:
        for k, v in q["usage"].items():
            usage[k] = usage.get(k, 0) + v
    cites = [c for r in records for c in r["citations"]]
    return {
        "judge": judge.id,
        **extra,
        "actions": actions,
        "model_calls": sum(q["calls"] for q in questions),
        "usage": usage,
        "citations": len(cites),
        "citations_rejected": sum(1 for c in cites if not c["ok"]),
        # 답을 받지 못한 질문(전송 실패·보내지 않음·읽을 수 없는 답). 그 단위는 정적 판정이 그대로 남고, 독립 검토에서는
        # 그 정책을 보지 못한 것이다
        "unanswered": sum(1 for q in questions if q["failure"]),
        "questions": questions,
        "records": records,
    }


def run_agent_pass(
    result,
    root: Path,
    pack,
    duties: dict[str, dict],
    judge: AgentJudge,
    files: list[Path],
    max_units: int | None = None,
) -> dict:
    """review 방식. `result`(EvalResult)의 findings 를 고친다. 반환값은 보고서 `run.agent` 에 실을 기록."""
    root = root.resolve()
    index = build_index(root, files)
    by_rel: dict[tuple[str, str], list] = {}
    plain = []
    for f in result.findings:
        r = rel(f.file, root)
        by_rel.setdefault((f.policy, r), []).append(f)
        plain.append({"policy": f.policy, "rule": f.rule, "file": r, "line": f.line, "outcome": f.outcome.value})
    units = candidate_units(plain, index)
    asked = units if max_units is None else units[:max_units]
    policies = {p.id: p for p in pack.policies}

    records, questions, cleared_ids, changed = [], [], set(), {}
    for policy_id in sorted({u.policy for u in asked}):
        mine = [u for u in asked if u.policy == policy_id]
        carried: list[dict] = []
        for start in range(0, len(mine), CHUNK):
            chunk = mine[start : start + CHUNK]
            q = _question(
                policies.get(policy_id),
                duties,
                policy_id,
                entries=tuple(Entry(u.entry, tuple(u.lines), tuple(u.related)) for u in chunk),
                carried=tuple(carried),
            )
            ans = judge.ask(q, root)
            qn = len(questions)
            questions.append(
                {
                    "n": qn,
                    "policy": policy_id,
                    "entries": [u.entry for u in chunk],
                    "carried": len(carried),
                    "failure": ans.failure,
                    "calls": ans.calls,
                    "stop_reason": ans.stop_reason,
                    "partial": ans.partial,
                    "tool_calls": ans.tool_calls,
                    "budget": ans.budget,
                    "usage": ans.usage,
                    "sent": _sent(ans),
                    **({"raw": ans.raw} if ans.failure == "parse" or ans.partial else {}),
                }
            )
            for u in chunk:
                res = None if ans.failure else ans.for_entry(u.entry)
                checked = gate(root, res.citations) if res else []
                verdict = res.verdict if res else "unknown"
                if verdict == "not-applicable":
                    # '해당 없음'은 진입 파일에 대한 말이다. 다른 파일의 줄은 그것을 보여 주지 못한다
                    for c in checked:
                        if c["ok"] and c["file"].removeprefix("./") != u.entry:
                            c["ok"], c["why"] = False, "not-entry-file"
                grounded = any(c["ok"] for c in checked)
                if res is None:
                    action = "kept-no-answer"
                elif verdict in ("compliant", "not-applicable"):
                    action = "cleared" if grounded else "kept-ungrounded"
                elif verdict == "not-compliant":
                    action = "confirmed"
                else:
                    action = "kept"
                if action == "cleared" and verdict == "compliant":
                    for c in checked:
                        if c["ok"] and len(carried) < CARRY and c not in carried:
                            carried.append(c)
                note = {
                    "verdict": verdict,
                    "action": action,
                    "reason": res.reason if res else "",
                    "citations": checked,
                    "question": qn,
                }
                findings = by_rel.get((u.policy, u.entry), [])
                for f in findings:
                    if action == "cleared":
                        cleared_ids.add(id(f))
                    else:
                        outcome = Outcome.NEEDS_REVIEW if action == "confirmed" else f.outcome
                        changed[id(f)] = replace(
                            f, outcome=outcome, agent=note, trace=[*f.trace, f"agent: {verdict} → {action}"]
                        )
                records.append(
                    {
                        **u.as_dict(),
                        **note,
                        "findings": [{"rule": f.rule, "line": f.line, "outcome": f.outcome.value} for f in findings],
                    }
                )
    result.findings = [changed.get(id(f), f) for f in result.findings if id(f) not in cleared_ids]
    return _summary(
        judge,
        records,
        questions,
        {"mode": "review", "units": len(units), "asked": len(asked), "index": index.summary()},
    )


def run_independent(
    root: Path,
    pack,
    duties: dict[str, dict],
    judge: AgentJudge,
    files: list[Path] | None = None,
    known: dict[str, list[str]] | None = None,
    rule: str = "agent-independent",
) -> tuple[list[Finding], dict]:
    """정적 경고 없이 정책마다 묻고, 판정기가 낸 '미충족'·'모름'을 경고로 만든다.

    independent(M3): `known` 없이 부른다. combined(M4 의 찾기 단계): 정적 검사·review 가 이미 본 파일을 `known`
    으로 주고, 그 밖에서 찾은 것만 경고로 더한다(rule 'agent-discovered').

    경고가 되려면
      - 진입 파일이 검사 대상(`files`, 보통 discover 가 고른 JS·TS 파일) 안에 있어야 한다. 다른 방식과 같은 범위에서
        비교하기 위해서다(dev 실측: 판정기가 Python 서버 파일과 문서 파일도 답했다).
      - 그 진입 파일의 줄을 인용해 관문을 통과해야 한다. 정적 신호 없이 판정기 말만으로 경고를 만들므로, 의무가 걸리는
        처리가 그 파일에 있다는 것은 보여야 한다.
    """
    from policypack.evaluate.engine import _law_of

    root = root.resolve()
    scope = None if files is None else {f.resolve().relative_to(root).as_posix() for f in files}
    known = known or {}
    findings: list[Finding] = []
    records, questions = [], []
    for pol in pack.policies:
        seen_before = tuple(sorted(known.get(pol.id, [])))
        q = _question(pol, duties, pol.id, mode="independent", known=seen_before)
        ans = judge.ask(q, root)
        qn = len(questions)
        questions.append(
            {
                "n": qn,
                "policy": pol.id,
                "known": len(seen_before),
                "failure": ans.failure,
                "calls": ans.calls,
                "stop_reason": ans.stop_reason,
                "partial": ans.partial,
                "tool_calls": ans.tool_calls,
                "budget": ans.budget,
                "usage": ans.usage,
                "sent": _sent(ans),
                "results": len(ans.results),
                **({"raw": ans.raw} if ans.failure == "parse" or ans.partial else {}),
            }
        )
        seen: set[str] = set(seen_before)
        for res in ans.results:
            entry = res.entry.lstrip("/")
            path = (root / entry).resolve()
            checked = gate(root, res.citations)
            own = any(c["ok"] and c["file"].removeprefix("./").lstrip("/") == entry for c in checked)
            inside = path == root or root in path.parents
            if not inside or not path.is_file():
                action = "dropped-no-file"
            elif scope is not None and entry not in scope:
                action = "dropped-out-of-scope"
            elif entry in seen_before:
                action = "dropped-known"
            elif entry in seen:
                action = "dropped-duplicate"
            elif res.verdict == "compliant":
                action = "compliant"
            elif not own:
                action = "dropped-ungrounded"
            elif res.verdict == "not-compliant":
                action = "warned"
            elif res.verdict == "unknown":
                action = "warned-uncertain"
            else:
                action = "not-applicable"
            seen.add(entry)
            note = {
                "verdict": res.verdict,
                "action": action,
                "reason": res.reason,
                "citations": checked,
                "question": qn,
            }
            records.append({"policy": pol.id, "entry": entry, "line": res.line, **note})
            if action.startswith("warned"):
                findings.append(
                    Finding(
                        policy=pol.id,
                        rule=rule,
                        outcome=Outcome.NEEDS_REVIEW if action == "warned" else Outcome.NEEDS_REVIEW_UNCERTAIN,
                        file=str(path),
                        category=pol.category,
                        title=pol.title,
                        law=_law_of(pol),
                        ask_developer=pol.ask_developer or "",
                        line=res.line,
                        trace=[f"agent({rule}): {res.verdict}"],
                        agent=note,
                    )
                )
    mode = "independent" if rule == "agent-independent" else "discover"
    return findings, _summary(judge, records, questions, {"mode": mode})

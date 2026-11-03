"""후보 단위 — 진입 파일 하나와 함께 볼 파일들.

정적 판정이 낸 경고(검토 필요·불확실)를 (정책, 진입 파일)로 묶고, 색인에서 함께 볼 파일을 붙인다.
에이전트형 판정기(방향 A, M4)는 이 단위를 받아 진입 파일에서 시작해 관련 파일을 읽는다. 판정은 하지 않는다.

같은 (정책, 파일)에 규칙이 여럿 걸리면 단위 하나로 묶는다. 의무는 정책에 붙고 판정기는 정책을 묻기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from policypack.index.graph import RepoIndex


@dataclass
class Unit:
    policy: str
    entry: str
    rules: list[str]
    outcomes: list[str]
    lines: list[int]
    role: str
    related: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "policy": self.policy,
            "entry": self.entry,
            "rules": self.rules,
            "outcomes": self.outcomes,
            "lines": self.lines,
            "role": self.role,
            "related": self.related,
        }


def candidate_units(findings: list[dict], index: RepoIndex, limit: int = 15) -> list[Unit]:
    """`findings` 는 JSON 보고서의 findings 꼴: [{policy, rule, file, line?, outcome}]. file 은 저장소 기준 경로."""
    groups: dict[tuple[str, str], dict] = {}
    for f in findings:
        g = groups.setdefault((f["policy"], f["file"]), {"rules": set(), "outcomes": set(), "lines": set()})
        g["rules"].add(f.get("rule", ""))
        g["outcomes"].add(f["outcome"])
        if isinstance(f.get("line"), int):
            g["lines"].add(f["line"])
    units = []
    for (policy, entry), g in sorted(groups.items()):
        role = index.roles.get(entry)
        units.append(
            Unit(
                policy=policy,
                entry=entry,
                rules=sorted(r for r in g["rules"] if r),
                outcomes=sorted(g["outcomes"]),
                lines=sorted(g["lines"]),
                role=role.value if role else "unknown",
                related=index.related(entry, limit=limit),
            )
        )
    return units

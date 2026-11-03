"""label.py 시험. 모델을 부르지 않는다(가짜 API).  실행: uv run pytest eval/run/test_label.py"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("label", Path(__file__).with_name("label.py"))
label = importlib.util.module_from_spec(spec)
spec.loader.exec_module(label)

POLICIES = [
    "kr.pipa.22-2",
    "kr.network-act.50-3",
    "kr.network-act.50-4",
    "kr.ai-basic-act.31",
    "kr.ai-basic-act.31-1",
    "kr.pipa.ai-transfer",
]


@pytest.fixture
def repo(tmp_path: Path) -> label.Repo:
    root = tmp_path / "o__r"
    (root / "src").mkdir(parents=True)
    (root / "src" / "Signup.tsx").write_text("const a = 1;\n  <input name='birth' />\nexport default a;\n")
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "i.js").write_text("birth")
    (tmp_path / "secret.txt").write_text("outside")
    (root / "src" / "link.txt").symlink_to(tmp_path / "secret.txt")
    return label.Repo(root)


def test_paths_stay_inside(repo):
    assert "저장소 밖" in repo.call("read_file", {"path": "../secret.txt"})
    assert "저장소 밖" in repo.call("list_files", {"path": "/../.."})
    assert "link.txt" not in repo.list_files()
    assert "outside" not in repo.search("outside")
    assert "node_modules" not in repo.search("birth")


def test_read_and_search(repo):
    assert repo.read_file("src/Signup.tsx", 2, 2) == "2\t  <input name='birth' />\n(전체 3줄)"
    assert repo.search("BIRTH") == "src/Signup.tsx:2: <input name='birth' />"
    assert repo.list_files(pattern="*.tsx") == "src/Signup.tsx"


def test_policy_sections_exist():
    guide = (label.GUIDE / "LABEL_GUIDE.md").read_text(encoding="utf-8")
    template = (label.GUIDE / "labeller-prompt.md").read_text(encoding="utf-8")
    for p in POLICIES:
        sec = label.policy_section(guide, p)
        assert sec.startswith(f"## 정책 {p}")
        assert "## 정책 " not in sec[5:]
        text = label.prompt(template, guide, "o/r", "src/a.ts", p)
        for ph in ("{{POLICY_SECTION}}", "{{REPO}}", "{{START_FILE}}", "{{POLICY_ID}}"):
            assert ph not in text


def test_parse_and_citations(repo):
    doc = label.parse(
        '앞글 {"x": 1} 그리고 {"label": "검토 필요", "citations": [{"file": "src/Signup.tsx", "line": 2, '
        '"text": "<input name=\'birth\' />"}, {"file": "src/Signup.tsx", "line": 3, "text": "틀림"}]}'
    )
    assert doc["label"] == "검토 필요"
    assert label.check_citations(repo, doc["citations"]) == [True, False]
    assert label.parse("답 없음") is None


class FakeApi:
    """도구를 끝없이 부르다가, 도구가 꺼지면 답한다."""

    def __init__(self):
        self.tool_flags = []

    def send(self, messages, tools):
        self.tool_flags.append(tools)
        n = len(self.tool_flags)
        if tools:
            content = [
                {"type": "tool_use", "id": f"t{n}a", "name": "read_file", "input": {"path": "src/Signup.tsx"}},
                {"type": "tool_use", "id": f"t{n}b", "name": "search", "input": {"pattern": "birth"}},
            ]
        else:
            content = [
                {"type": "text", "text": json.dumps({"label": "검토 필요", "citations": []}, ensure_ascii=False)}
            ]
        return {"content": content, "stop_reason": "x", "usage": {"input_tokens": 10, "output_tokens": 5}}


def test_budget(repo):
    api = FakeApi()
    res = label.label_unit(api, repo, "질문")
    assert res["tool_calls"] == 30
    assert api.tool_flags == [True] * 15 + [False]
    assert label.parse(res["answer_text"])["label"] == "검토 필요"
    assert res["usage"] == {"input_tokens": 160, "output_tokens": 80}


def test_cache_mark_and_price():
    msgs = [{"role": "user", "content": "a"}]
    out = label.cached(msgs)
    assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert msgs[0]["content"] == "a"
    assert label.price("claude-opus-5-5", {"input_tokens": 1_000_000}) == 15.0


def test_disputed_block():
    assert label.disputed_block({"file": "a", "policy": "p"}) == ""
    u = {
        "answers": [
            {"label_ko": "검토 필요", "reason": "r1", "citations": [{"file": "a.ts", "line": 3, "text": "x()"}]},
            {"label_ko": "충족 근거 있음", "reason": "r2", "citations": []},
        ]
    }
    text = label.disputed_block(u)
    assert (
        "두 라벨러의 답이 갈렸다" in text
        and "답 1: 검토 필요 — r1 (인용: a.ts:3 x())" in text
        and "답 2: 충족 근거 있음" in text
    )

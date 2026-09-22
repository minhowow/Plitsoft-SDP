"""`--staged` 와 `--diff` — 커밋 전 훅과 CI 에서 바뀐 파일만 본다."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from policypack import gitscope
from policypack.cli import main

VIOLATING = (
    'export async function blast(users) {\n  for (const u of users) await sms.send(u.phone, "(광고) 가을 세일");\n}\n'
)
CLEAN = "export const add = (a, b) => a + b;\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.js").write_text(CLEAN, encoding="utf-8")
    (tmp_path / "b.js").write_text(CLEAN, encoding="utf-8")
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_staged_picks_only_staged_files(repo):
    (repo / "a.js").write_text(VIOLATING, encoding="utf-8")
    (repo / "b.js").write_text(VIOLATING, encoding="utf-8")  # 바뀌었지만 스테이징 안 함
    git(repo, "add", "a.js")
    scope = gitscope.staged(repo)
    assert [p.name for p in scope.files] == ["a.js"]


def test_deleted_files_are_not_scanned(repo):
    (repo / "a.js").unlink()
    git(repo, "add", "-A")
    assert gitscope.staged(repo).files == []


def test_diff_includes_uncommitted_changes(repo):
    (repo / "a.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "commit", "-qam", "change a")
    (repo / "b.js").write_text(VIOLATING, encoding="utf-8")  # 커밋 안 한 변경도 잡혀야 한다
    scope = gitscope.changed_since(repo, "HEAD~1")
    assert sorted(p.name for p in scope.files) == ["a.js", "b.js"]


def test_bad_ref_is_a_tool_error(repo, capsys):
    assert main(["scan", "--diff", "no-such-ref", "--no-color"]) == 2
    assert "git" in capsys.readouterr().err


def test_scan_staged_reports_only_staged(repo, capsys):
    (repo / "a.js").write_text(VIOLATING, encoding="utf-8")
    (repo / "b.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "a.js")
    code = main(["scan", "--staged", "--no-color", "--output-format", "concise"])
    out = capsys.readouterr()
    assert code == 1
    assert "a.js" in out.out and "b.js" not in out.out
    assert "스테이징된 파일 1개" in out.err


def test_nothing_staged_is_not_an_error(repo, capsys):
    assert main(["scan", "--staged", "--no-color"]) == 0
    assert "검사할 파일이 없습니다" in capsys.readouterr().err


def test_non_code_files_are_ignored(repo, capsys):
    (repo / "README.md").write_text("# 바뀜\n", encoding="utf-8")
    git(repo, "add", "README.md")
    assert main(["scan", "--staged", "--no-color"]) == 0


def test_dirty_staged_file_is_warned(repo, capsys):
    """스테이징한 뒤 또 고친 파일은 작업 트리와 커밋될 내용이 다르다. 말해 줘야 한다."""
    (repo / "a.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "a.js")
    (repo / "a.js").write_text(VIOLATING + "// 또 고침\n", encoding="utf-8")
    main(["scan", "--staged", "--no-color", "--output-format", "concise"])
    assert "커밋될 내용과 다를 수 있습니다" in capsys.readouterr().err


def test_path_argument_narrows_the_scope(repo, capsys):
    (repo / "sub").mkdir()
    (repo / "sub" / "c.js").write_text(VIOLATING, encoding="utf-8")
    (repo / "a.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "-A")
    main(["scan", "--staged", "sub", "--no-color", "--output-format", "concise"])
    out = capsys.readouterr().out
    assert "c.js" in out and "a.js" not in out


# ── 심볼릭 링크 ─────────────────────────────────────────────────────────────
# semgrep 은 링크를 대상으로 받지 않는다(Invalid scanning root). 넘기면 도구 전체가
# "정책 팩이 잘못됐다"는 엉뚱한 설명과 함께 exit 2 로 끝나 커밋이 막힌다.


def test_staged_symlink_is_not_a_tool_error(repo, capsys):
    (repo / "link.js").symlink_to("a.js")
    git(repo, "add", "link.js")
    assert main(["scan", "--staged", "--no-color"]) == 0, capsys.readouterr().err


def test_committed_symlink_is_not_a_tool_error(repo, capsys):
    """커밋된 심볼릭 링크가 있어도 범위 검사와 전체 검사가 도구 오류로 끝나지 않는다."""
    (repo / "config").mkdir()
    (repo / "config" / "base.js").write_text(CLEAN, encoding="utf-8")
    (repo / "app.config.js").symlink_to("config/base.js")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "link")
    (repo / "a.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "a.js")
    assert main(["scan", "--staged", "--no-color"]) == 1, capsys.readouterr().err
    assert main(["scan", ".", "--no-color"]) == 1


def test_symlink_replaced_by_a_file_is_scanned(repo):
    """종류가 바뀐 변경(T)도 검사할 내용이 있다."""
    (repo / "h.js").symlink_to("a.js")
    git(repo, "add", "h.js")
    git(repo, "commit", "-qm", "link")
    (repo / "h.js").unlink()
    (repo / "h.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "h.js")
    assert [p.name for p in gitscope.staged(repo).files] == ["h.js"]


# ── 어느 저장소, 어느 범위 ──────────────────────────────────────────────────


def test_path_argument_picks_its_own_repo(repo, tmp_path_factory, capsys):
    """cwd 의 저장소 인덱스를 보면 다른 저장소의 변경을 하나도 못 보고 exit 0 으로 통과한다."""
    other = tmp_path_factory.mktemp("other")
    git(other, "init", "-q")
    (other / "q.js").write_text(VIOLATING, encoding="utf-8")
    git(other, "add", "q.js")
    assert main(["scan", "--staged", str(other), "--no-color", "--output-format", "concise"]) == 1
    assert "q.js" in capsys.readouterr().out


def test_nested_repo_is_scoped_by_its_own_index(repo, capsys):
    nested = repo / "nested"
    nested.mkdir()
    git(nested, "init", "-q")
    (nested / "q.js").write_text(VIOLATING, encoding="utf-8")
    git(nested, "add", "q.js")
    assert main(["scan", "--staged", "nested", "--no-color"]) == 1


def test_paths_in_two_repos_are_refused(repo, tmp_path_factory, capsys):
    other = tmp_path_factory.mktemp("other")
    git(other, "init", "-q")
    assert main(["scan", "--staged", ".", str(other), "--no-color"]) == 2
    assert "서로 다른 git 저장소" in capsys.readouterr().err


def test_dot_and_dot_slash_mean_the_same(repo, monkeypatch, capsys):
    """기본값과 사용자가 쓴 '.' 를 문자열로 가르면 '.' 와 './' 가 다른 범위가 된다."""
    (repo / "sub").mkdir()
    (repo / "sub" / "c.js").write_text(CLEAN, encoding="utf-8")
    (repo / "b.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "-A")
    monkeypatch.chdir(repo / "sub")
    assert main(["scan", "--staged", ".", "--no-color"]) == 0
    assert main(["scan", "--staged", "./", "--no-color"]) == 0
    assert main(["scan", "--staged", "--no-color"]) == 1, "경로가 없으면 저장소 전체다"


def test_report_paths_are_repo_relative_from_a_subfolder(repo, monkeypatch, capsys):
    """GitHub 은 SARIF uri 를 저장소 루트 기준으로 읽는다. 지문도 실행 위치와 무관해야 한다."""
    (repo / "sub").mkdir()
    (repo / "sub" / "a b.js").write_text(VIOLATING, encoding="utf-8")
    (repo / "top.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "-A")

    def sarif() -> dict:
        main(["scan", "--staged", "--output-format", "sarif"])
        res = json.loads(capsys.readouterr().out)["runs"][0]["results"]
        return {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]: r["partialFingerprints"] for r in res}

    at_root = sarif()
    monkeypatch.chdir(repo / "sub")
    assert sarif() == at_root
    assert set(at_root) == {"sub/a b.js", "top.js"}


def test_empty_scope_still_writes_a_valid_report(repo, capsys):
    """CI 의 SARIF 업로드 단계는 빈 stdout 을 받으면 실패한다."""
    (repo / "README.md").write_text("# 바뀜\n", encoding="utf-8")
    git(repo, "add", "README.md")
    assert main(["scan", "--staged", "--output-format", "sarif"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["version"] == "2.1.0" and doc["runs"][0]["results"] == []
    assert main(["scan", "--staged", "--output-format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == []


def test_scope_applies_the_same_size_limit_as_a_full_scan(repo, monkeypatch, capsys):
    """같은 파일의 판정이 어떻게 돌렸느냐에 따라 달라지면 안 된다."""
    import policypack.discover as d

    monkeypatch.setattr(d, "MAX_BYTES", 10)
    (repo / "a.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "a.js")
    assert main(["scan", "--staged", "--no-color", "--output-format", "json"]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["run"]["skipped"] == ["a.js"]
    assert "1MB 초과 1개" in out.err


def test_repo_under_a_build_directory_is_not_skipped(tmp_path, monkeypatch):
    """SKIP_DIRS 는 검사 루트 아래에서만 본다. 저장소가 ~/build/app 에 있다고 전부 빼면 안 된다."""
    from policypack.discover import discover

    proj = tmp_path / "build" / "proj"
    proj.mkdir(parents=True)
    git(proj, "init", "-q")
    (proj / "helper.js").write_text(CLEAN, encoding="utf-8")
    (proj / "node_modules").mkdir()
    (proj / "node_modules" / "dep.js").write_text(CLEAN, encoding="utf-8")
    assert [p.name for p in discover([proj], ["javascript"]).files] == ["helper.js"]


def test_korean_file_names_survive(repo, capsys):
    (repo / "회원가입.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "-A")
    assert [p.name for p in gitscope.staged(repo).files] == ["회원가입.js"]
    assert main(["scan", "--staged", "--no-color"]) == 1


# ── --diff ──────────────────────────────────────────────────────────────────


def test_diff_compares_against_the_merge_base(repo):
    """main 에 나중에 들어온 남의 변경으로 PR 이 실패하면 안 된다."""
    git(repo, "branch", "-M", "main")
    git(repo, "checkout", "-qb", "feature")
    (repo / "feature.js").write_text(CLEAN, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "feature")
    git(repo, "checkout", "-q", "main")
    (repo / "b.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "commit", "-qam", "main 쪽 변경")
    git(repo, "checkout", "-q", "feature")
    assert [p.name for p in gitscope.changed_since(repo, "main").files] == ["feature.js"]


def test_diff_includes_untracked_new_files(repo):
    (repo / "new.js").write_text(VIOLATING, encoding="utf-8")
    (repo / ".gitignore").write_text("ignored.js\n", encoding="utf-8")
    (repo / "ignored.js").write_text(VIOLATING, encoding="utf-8")
    names = sorted(p.name for p in gitscope.changed_since(repo, "HEAD").files)
    assert names == [".gitignore", "new.js"]


def test_diff_ref_that_is_also_a_folder_name(repo):
    """'--' 가 없으면 git 이 ref 인지 경로인지 헷갈려 실패한다."""
    git(repo, "branch", "release")
    (repo / "release").mkdir()
    (repo / "release" / "x.js").write_text(VIOLATING, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "x")
    assert [p.name for p in gitscope.changed_since(repo, "release").files] == ["x.js"]


def test_bad_ref_error_says_what_went_wrong(repo, capsys):
    assert main(["scan", "--diff", "no-such-ref", "--no-color"]) == 2
    err = capsys.readouterr().err
    assert "no-such-ref" in err and "커밋으로 풀리지 않는" in err


def test_ref_that_looks_like_an_option_is_not_an_option(repo, capsys):
    target = repo / "written-by-git"
    assert main(["scan", f"--diff=--output={target}", "--no-color"]) == 2
    assert not target.exists()

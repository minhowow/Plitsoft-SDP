"""git 으로 검사 범위를 좁힌다 — `--staged` 와 `--diff`.

커밋 전 훅에서는 저장소 전체가 아니라 **이번에 바뀐 파일**만 보는 게 관습이다.
pre-commit 은 파일 목록을 인자로 넘겨주므로 이게 필요 없지만, husky·lefthook 같은
다른 훅 관리자나 CI 에서는 CLI 가 직접 범위를 정해야 한다.

## 무엇을 검사하나

작업 트리의 파일을 검사한다. pre-commit 은 스테이징하지 않은 변경을 잠시 치워 두고
훅을 돌리므로 그 경우 작업 트리가 곧 스테이징된 내용이다. 직접 `--staged` 로 돌렸는데
스테이징하지 않은 변경이 남아 있으면 둘이 다를 수 있어서, 그때는 경고한다.

## `--diff REF` 는 분기점과 비교한다

PR 검사에서 알고 싶은 것은 "이 브랜치가 바꾼 파일"이다. REF 의 끝과 비교하면 그 사이
main 에 들어온 남의 변경까지 범위에 들어와, PR 이 건드리지도 않은 파일로 CI 가 실패한다.
그래서 `git merge-base REF HEAD` 를 구해 거기서부터 작업 트리까지를 본다(세 점 `...`
의 뜻). 커밋하지 않은 변경과 아직 add 하지 않은 새 파일도 포함한다.

## 파일 이름은 바이트로 받는다

git 은 파일 이름을 바이트로 낸다. `text=True` 로 받으면 로캘 인코딩으로 디코드해서,
CP949 환경의 한글 파일 이름이 깨지거나 예외가 난다. `os.fsdecode` 는 파일 시스템
인코딩으로 풀고, 못 푸는 바이트는 surrogateescape 로 보존해 다시 같은 파일을 연다.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from policypack.errors import ConfigError


@dataclass
class Scope:
    files: list[Path] = field(default_factory=list)
    root: Path | None = None
    label: str = ""
    dirty: list[Path] = field(default_factory=list)
    """스테이징된 뒤 작업 트리에서 또 바뀐 파일. 검사 내용이 커밋될 내용과 다를 수 있다."""


def _git(args: list[str], cwd: Path) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=60)
    except FileNotFoundError as e:
        raise ConfigError("git 을 찾을 수 없습니다. --staged / --diff 는 git 저장소에서만 됩니다.") from e
    except subprocess.TimeoutExpired as e:
        raise ConfigError(f"git {' '.join(args)} 이 60초 안에 끝나지 않았습니다") from e
    if out.returncode != 0:
        err = out.stderr.decode("utf-8", "replace").strip()
        raise ConfigError(f"git {' '.join(args)} 실패: {err[:300] or f'종료 코드 {out.returncode}'}")
    return os.fsdecode(out.stdout)


def repo_root(start: Path) -> Path:
    try:
        return Path(_git(["rev-parse", "--show-toplevel"], start).strip())
    except ConfigError as e:
        if "not a git repository" not in str(e):
            raise
        raise ConfigError(f"git 저장소가 아닙니다: {start}. --staged·--diff 는 git 저장소에서만 씁니다.") from e


def _names(output: str, root: Path) -> list[Path]:
    return [root / line for line in output.split("\0") if line]


#: 검사할 내용이 남는 변경. 추가·복사·수정·이름 바꿈·종류 바뀜(링크 → 파일). 지운 것은 뺀다.
DIFF_FILTER = "--diff-filter=ACMRT"


def staged(start: Path) -> Scope:
    """스테이징된 파일. 지운 파일은 뺀다(검사할 내용이 없다)."""
    root = repo_root(start)
    files = _names(_git(["diff", "--cached", "--name-only", "-z", DIFF_FILTER], root), root)
    unstaged = set(_names(_git(["diff", "--name-only", "-z"], root), root))
    return Scope(files=files, root=root, label="스테이징된 파일", dirty=[f for f in files if f in unstaged])


def changed_since(start: Path, ref: str) -> Scope:
    """`ref` 와의 분기점 이후 이 브랜치에서 바뀐 파일.

    커밋한 변경, 커밋하지 않은 변경, add 하지 않은 새 파일(.gitignore 제외)을 모두 넣는다.
    """
    root = repo_root(start)
    try:
        # --end-of-options: '-' 로 시작하는 ref 를 옵션으로 읽지 않게 한다
        _git(["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], root)
    except ConfigError as e:
        raise ConfigError(
            f"--diff {ref}: 커밋으로 풀리지 않는 ref 입니다. 브랜치·태그·커밋을 주세요. "
            f"CI 라면 그 ref 를 fetch 했는지 확인하세요.\n  ({e})"
        ) from None
    try:
        base = _git(["merge-base", "--end-of-options", ref, "HEAD"], root).strip()
    except ConfigError as e:
        raise ConfigError(
            f"--diff {ref}: HEAD 와의 분기점을 찾지 못했습니다. 얕은 복제라면 "
            f"fetch-depth: 0 으로 체크아웃하거나 git fetch --unshallow 를 돌리세요.\n  ({e})"
        ) from None
    # '--' 뒤에 경로가 없어도 붙인다. 같은 이름의 폴더가 있으면 git 이 ref 인지 경로인지 헷갈린다.
    tracked = _names(_git(["diff", "--name-only", "-z", DIFF_FILTER, "--end-of-options", base, "--"], root), root)
    untracked = _names(_git(["ls-files", "--others", "--exclude-standard", "-z"], root), root)
    label = f"{ref} 와의 분기점({base[:7]}) 이후 바뀐 파일"
    return Scope(files=sorted(set(tracked) | set(untracked)), root=root, label=label)


def within(files: list[Path], prefixes: list[Path]) -> list[Path]:
    """경로 인자가 주어졌으면 그 아래 파일로 더 좁힌다."""
    roots = [p.resolve() for p in prefixes]
    out = []
    for f in files:
        r = f.parent.resolve() / f.name  # 링크 자체의 위치로 판단한다. 링크를 따라가지 않는다
        if any(r == p or p in r.parents for p in roots):
            out.append(f)
    return out

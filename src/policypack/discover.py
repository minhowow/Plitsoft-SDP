"""검사할 파일을 우리가 정한다.

semgrep 에 디렉터리를 넘기면 자체 규칙으로 경로를 걸러 낸다. 실측에서 이름이
`test` 인 디렉터리가 통째로 빠졌다. 법 검토 도구가 사용자의 test 디렉터리를 말없이
건너뛰면 쓸모가 없다.

그래서 여기서 목록을 만들고 백엔드에는 **파일만** 넘긴다. 무엇을 뺐는지도 셀 수 있다.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from policypack.static.compile import LANGUAGE_GLOBS

#: 들어가 봐야 소용없는 디렉터리. 사용자 코드가 아니다.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".output",
        "coverage",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "vendor",
        # Yarn Berry 가 만든 것(플러그인·릴리스·SDK·PnP 캐시). 사용자 코드가 아니다
        ".yarn",
    }
)

MAX_BYTES = 1_000_000
"""이보다 큰 파일은 건너뛴다. semgrep 기본값과 같다. 대개 번들·생성물이다."""

#: 축소·번들된 생성물. 크기로는 걸러지지 않는 것들이 있다.
#:
#: SKIP_DIRS 가 dist·build·vendor 를 빼는 것과 같은 이유다. 축소된 파일은 한 줄에 수만
#: 자라 검토할 수도, 고칠 수도 없다(고치려면 원본을 고친다). 1MB 미만인 것이 많아
#: MAX_BYTES 로는 걸러지지 않는다.
#:
#: **시험 디렉터리는 빼지 않는다.** 이 모듈의 첫 문단이 그 이유를 적는다.
GENERATED_SUFFIXES = (
    ".min.js",
    ".min.mjs",
    ".min.cjs",
    ".bundle.js",
    ".min.jsx",
    ".min.ts",
    ".min.tsx",
    # Yarn Plug'n'Play 가 저장소 루트에 만드는 해석기. 사용자 코드가 아니다
    ".pnp.cjs",
    ".pnp.js",
    ".pnp.loader.mjs",
)


ENGINE_UNREADABLE: dict[str, str] = {".mts": ".ts", ".cts": ".ts"}
"""고정한 Semgrep(1.176.1)이 언어로 알아보지 못하는 확장자 → 그 언어의 대표 확장자.

이런 파일을 검사 대상에 넣으면 언어 규칙이 돌지 않고 오류도 남기지 않는다. 그래서 구문 조건이 조용히
'거짓'이 되고 보고서는 다 봤다고 말했다. 같은 위반 코드가 .ts 에서는 경고 5건, .mts 에서는 0건이었다
(실측). 검사하지 않은 파일로 알린다."""

ENGINE_EXTS = frozenset(g.lstrip("*") for globs in LANGUAGE_GLOBS.values() for g in globs)
"""우리가 언어를 아는 확장자 가운데 엔진이 읽는 철자. 대소문자를 가린다 — Semgrep 은 Mail.TS·a.Ts 를 이름을
대도 읽지 않고 오류도 남기지 않는다(실측)."""


def engine_skips(path: Path) -> bool:
    """우리가 아는 언어의 파일인데(.mts·.cts, 대소문자만 다른 .TS·.Jsx 등) 고정한 엔진이 읽지 않는 철자인가.

    모르는 확장자(.sh·.kt·.yaml 등)는 여기에 들지 않는다. 이름을 대서 준 파일은 확장자와 무관하게 엔진에
    넘기고, 읽을지는 엔진이 정한다."""
    suffix = path.suffix
    known = suffix.lower() in ENGINE_EXTS or suffix.lower() in ENGINE_UNREADABLE
    return known and suffix not in ENGINE_EXTS


@dataclass
class Discovery:
    files: list[Path] = field(default_factory=list)
    skipped_big: list[Path] = field(default_factory=list)
    skipped_generated: list[Path] = field(default_factory=list)
    skipped_unreadable: list[Path] = field(default_factory=list)
    """읽을 권한이 없는 파일. semgrep 은 이런 대상이 하나라도 있으면 출력 없이 끝나 검사 전체가 실패한다(실측)."""
    skipped_engine: list[Path] = field(default_factory=list)
    """엔진이 언어로 알아보지 못하는 확장자의 파일(ENGINE_UNREADABLE)."""
    skipped_links: int = 0

    def __len__(self) -> int:
        return len(self.files)

    def skipped_files(self) -> list[Path]:
        """보고서에 '검사하지 않음'으로 적을 파일. 같은 파일을 두 경로로 만났어도 한 번만 적고, 다른 경로로
        검사한 파일(이름을 대서 넣은 축소 파일 등)은 적지 않는다."""
        out, seen = [], {f.resolve() for f in self.files}
        for p in self.skipped_big + self.skipped_generated + self.skipped_unreadable + self.skipped_engine:
            if p.resolve() not in seen:
                seen.add(p.resolve())
                out.append(p)
        return out


def extensions_for(languages: list[str]) -> set[str]:
    out = set()
    for lang in languages:
        out |= {g.lstrip("*") for g in LANGUAGE_GLOBS.get(lang, [])}
    return out


def admit(path: Path, root: Path, exts: set[str]) -> str:
    """파일 하나를 검사 대상에 넣을지. 전체 검사와 --staged·--diff 가 같은 규칙을 쓴다.

    "ok" · "ext"(확장자가 안 맞음) · "dir"(생성물 디렉터리 아래) · "gen"(축소·번들 파일) ·
    "link" · "big" · "unreadable" · "gone" · "engine"(엔진이 읽지 못하는 확장자).

    확장자는 대소문자 없이 견줘 팩의 언어인지 보고(Mail.TS 도 TypeScript 파일이다), 엔진이 읽는지는
    대소문자를 가려 본다(ENGINE_EXTS). 팩의 언어인데 엔진이 읽지 못하면 "engine" 이다.

    - SKIP_DIRS 는 **검사 루트 아래의 상대 경로**로 본다. 저장소가 `~/build/app` 에
      있다고 저장소 전체를 빼면 안 된다.
    - 심볼릭 링크는 뺀다. semgrep 은 링크를 대상으로 받지 않고(Invalid scanning root)
      도구 전체가 오류로 끝난다. 링크가 가리키는 파일은 제 경로로 검사된다.
    """
    suffix = path.suffix.lower()
    if suffix not in exts and ENGINE_UNREADABLE.get(suffix) not in exts:
        return "ext"
    try:
        rel = path.relative_to(root) if path.is_absolute() == root.is_absolute() else path
    except ValueError:
        rel = path
    if SKIP_DIRS & set(rel.parts[:-1]):
        return "dir"
    if path.name.endswith(GENERATED_SUFFIXES):
        return "gen"
    if path.is_symlink():
        return "link"
    try:
        st = path.stat()
    except OSError:
        return "gone"
    if not path.is_file():
        return "gone"
    if st.st_size > MAX_BYTES:
        return "big"
    if not os.access(path, os.R_OK):
        return "unreadable"
    if engine_skips(path):
        return "engine"
    return "ok"


def _git_files(root: Path) -> list[Path] | None:
    """git 저장소면 추적 중인 파일 목록을 쓴다. .gitignore 를 그대로 따른다.

    이름은 바이트로 받아 파일 시스템 인코딩으로 푼다. 로캘 인코딩으로 풀면 한글 파일
    이름이 깨져서 말없이 빠진다.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            timeout=60,
        )
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0:
        return None
    # 지운 채 커밋하지 않은 파일도 --cached 에 남는다. admit 이 "gone" 으로 거른다.
    return [root / p for p in os.fsdecode(out.stdout).split("\0") if p]


def discover(paths: list[Path], languages: list[str], use_git: bool = True) -> Discovery:
    """검사 대상 파일 목록.

    파일을 직접 지정하면 확장자와 무관하게 받는다. 사용자가 명시한 것을 거르지 않는다.
    다만 심볼릭 링크면 가리키는 파일을 검사하고, 아는 언어인데 엔진이 읽지 못하는 철자(engine_skips)면 검사하지
    않은 파일로 알린다. 넘기면 엔진이 말없이 건너뛰어 '다 봤다'가 된다.
    """
    exts = extensions_for(languages)
    found = Discovery()
    seen: set[Path] = set()
    skipped_seen: set[Path] = set()

    for given in paths:
        p = Path(given)
        if p.is_file():
            if p.is_symlink():
                p = p.resolve()
            if engine_skips(p):
                # 이름을 댔어도 엔진이 읽지 못한다. 검사한 것으로 세면 조용히 '거짓'이 된다
                if p.resolve() not in skipped_seen:
                    skipped_seen.add(p.resolve())
                    found.skipped_engine.append(p)
                continue
            if p.resolve() not in seen:
                seen.add(p.resolve())
                found.files.append(p)
            continue
        if not p.is_dir():
            continue

        candidates = _git_files(p) if use_git else None
        if candidates is None:
            candidates = [c for c in p.rglob("*") if c.is_symlink() or not c.is_dir()]

        for child in candidates:
            verdict = admit(child, p, exts)
            if verdict in ("big", "gen", "unreadable", "engine"):
                # 같은 파일을 두 경로(폴더와 그 안의 파일 등)로 만나도 건너뛴 목록에는 한 번만 넣는다
                if child.resolve() in skipped_seen:
                    continue
                skipped_seen.add(child.resolve())
            if verdict == "link":
                found.skipped_links += 1
            elif verdict == "big":
                found.skipped_big.append(child)
            elif verdict == "gen":
                found.skipped_generated.append(child)
            elif verdict == "unreadable":
                found.skipped_unreadable.append(child)
            elif verdict == "engine":
                found.skipped_engine.append(child)
            if verdict != "ok" or child.resolve() in seen:
                continue
            seen.add(child.resolve())
            found.files.append(child)

    found.files.sort()
    return found


def language_of(path: Path) -> str:
    """확장자로 언어를 정한다. 정책 팩의 languages 와 맞춘다."""
    for lang, globs in LANGUAGE_GLOBS.items():
        if path.suffix in {g.lstrip("*") for g in globs}:
            return lang
    return "generic"

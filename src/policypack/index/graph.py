"""import 관계와 '함께 볼 파일' 고르기.

import 를 읽는 법: 정규식으로 `import … from 'x'`, `import 'x'`, `export … from 'x'`, `require('x')`, `import('x')`
의 문자열을 뽑는다. 주석 속 import 도 잡힐 수 있다(후보를 넓히는 쪽이라 둔다).

경로를 푸는 법(앞에서부터):
  1. 상대 경로(./, ../)
  2. 가장 가까운 tsconfig.json·jsconfig.json 의 compilerOptions.paths·baseUrl (extends 는 상대 경로만 따라간다)
  3. 흔한 별칭 '@/'·'~/' → 패키지 폴더의 src/ 또는 패키지 폴더
  확장자: 그대로, .ts .tsx .js .jsx .mjs .cjs .mts .cts .vue .svelte, 폴더면 index.*. TS 의 './a.js' 는 a.ts 로도 푼다.
패키지 폴더는 그 파일에서 가장 가까운 package.json 이 있는 폴더다(모노레포에서 앱을 가른다).
풀리지 않는 지정자(npm 패키지 등)는 `external` 로 따로 센다. css·이미지·json 같은 자원 import 는 세지 않는다.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from policypack.index.roles import Role, classify

_IMPORT = re.compile(
    r"""(?:^|[^\w$.])(?:import|export)\s(?:[^'";]*?\sfrom\s*)?['"]([^'"\n]+)['"]"""
    r"""|\b(?:require|import)\s*\(\s*['"]([^'"\n]+)['"]\s*\)""",
    re.M,
)
EXTS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte")
READ_BYTES = 400_000
#: 코드가 아닌 자원. import 해도 간선을 만들지 않고 못 푼 것으로도 세지 않는다.
_ASSET = re.compile(
    r"\.(css|scss|sass|less|svg|png|jpe?g|gif|webp|avif|ico|bmp|json|md|mdx|txt|html|woff2?|ttf|otf|eot|mp[34]|wav|webm|lottie|graphql|gql|ya?ml)(\?.*)?$",
    re.I,
)
_SHELL = re.compile(r"(^|/)(_app|_document|layout|App|app|main|root|Root)\.[cm]?[jt]sx?$")
#: 상수·타입·스타일·아이콘. 고지나 동의가 들어 있을 일이 드물어 맨 뒤로 보낸다.
_LOW = re.compile(
    r"(^|/)(constants?|types?|typings|styles?|icons?|assets|theme|themes|colors?|fonts?)(/|\.)|\.(types?|d|styles?)\.[cm]?[jt]sx?$",
    re.I,
)
_LEGAL = re.compile(r"terms|privacy|policy|policies|consent|agree|legal|약관|개인정보|동의", re.I)


@dataclass
class RepoIndex:
    root: Path
    files: list[str]
    roles: dict[str, Role]
    imports: dict[str, set[str]]
    importers: dict[str, set[str]]
    package: dict[str, str]
    external: dict[str, set[str]] = field(default_factory=dict)
    unresolved: dict[str, set[str]] = field(default_factory=dict)

    def summary(self) -> dict:
        roles: dict[str, int] = {}
        for r in self.roles.values():
            roles[r.value] = roles.get(r.value, 0) + 1
        return {
            "files": len(self.files),
            "roles": dict(sorted(roles.items())),
            "edges": sum(len(v) for v in self.imports.values()),
            "unresolved_local": sum(len(v) for v in self.unresolved.values()),
            "packages": len(set(self.package.values())),
        }

    def related(self, entry: str, depth: int = 2, limit: int = 15) -> list[dict]:
        """`entry` 와 함께 볼 파일들. [{file, why}] — why 는 imports·imported-by·legal·shell·hop2·low.

        순서: 직접 가져오는 파일, 직접 가져다 쓰는 파일, 같은 패키지의 약관·처리방침·동의 파일(3개까지), 같은 패키지의
        앱 껍데기(_app·layout 등, 2개까지), 두 걸음 떨어진 파일, 마지막으로 상수·타입·스타일 파일(`low`).
        고지·동의는 껍데기와 약관 화면에 있는 일이 많아 두 걸음 파일보다 앞에 둔다.
        시험 파일은 entry 가 시험 파일일 때만 넣는다.
        """
        if entry not in self.roles:
            return []
        keep_tests = self.roles[entry] is Role.TEST
        pkg = self.package.get(entry)
        out: list[dict] = []
        seen = {entry}
        low: list[str] = []

        def add(f: str, why: str) -> None:
            if f in seen or len(out) >= limit:
                return
            if self.roles.get(f) is Role.TEST and not keep_tests:
                return
            if why != "low" and _LOW.search(f):
                if f not in low:
                    low.append(f)
                return
            seen.add(f)
            out.append({"file": f, "why": why})

        first = sorted(self.imports.get(entry, ()))
        back = sorted(self.importers.get(entry, ()))
        for f in first:
            add(f, "imports")
        for f in back:
            add(f, "imported-by")
        same = [f for f in self.files if self.package.get(f) == pkg]
        for f in sorted((f for f in same if _LEGAL.search(f)), key=lambda f: (f.count("/"), f))[:3]:
            add(f, "legal")
        for f in sorted((f for f in same if _SHELL.search(f)), key=lambda f: (f.count("/"), f))[:2]:
            add(f, "shell")
        frontier = deque((f, 1) for f in [*first, *back])
        while frontier and len(out) < limit:
            f, d = frontier.popleft()
            if d >= depth:
                continue
            for g in [*sorted(self.imports.get(f, ())), *sorted(self.importers.get(f, ()))]:
                if g not in seen:
                    add(g, "hop2")
                    frontier.append((g, d + 1))
        for f in low:
            add(f, "low")
        return out


def _strip_jsonc(text: str) -> str:
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


class _Configs:
    """폴더 → 그 폴더에서 쓰일 (baseUrl 폴더, paths). tsconfig·jsconfig 을 한 번씩만 읽는다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.cache: dict[str, tuple[str | None, dict] | None] = {}

    def _read(self, rel_file: str, hops: int = 0) -> tuple[str | None, dict] | None:
        try:
            doc = json.loads(_strip_jsonc((self.root / rel_file).read_text(encoding="utf-8", errors="replace")))
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict):
            return None
        base_dir = posixpath.dirname(rel_file)
        parent: tuple[str | None, dict] | None = None
        ext = doc.get("extends")
        if isinstance(ext, str) and ext.startswith(".") and hops < 3:
            target = posixpath.normpath(posixpath.join(base_dir, ext))
            if not target.endswith(".json"):
                target += ".json"
            parent = self._read(target, hops + 1)
        opts = doc.get("compilerOptions") if isinstance(doc.get("compilerOptions"), dict) else {}
        base_url, paths = parent if parent else (None, {})
        if isinstance(opts.get("baseUrl"), str):
            base_url = posixpath.normpath(posixpath.join(base_dir, opts["baseUrl"]))
        if isinstance(opts.get("paths"), dict):
            anchor = base_url if base_url is not None else base_dir
            paths = {
                k: [posixpath.normpath(posixpath.join(anchor, t)) for t in v if isinstance(t, str)]
                for k, v in opts["paths"].items()
                if isinstance(v, list)
            }
        return base_url, paths

    def for_dir(self, d: str) -> tuple[str | None, dict] | None:
        if d in self.cache:
            return self.cache[d]
        found = None
        for name in ("tsconfig.json", "jsconfig.json"):
            rel = posixpath.join(d, name) if d not in ("", ".") else name
            if (self.root / rel).is_file():
                found = self._read(rel)
                break
        if found is None and d not in ("", "."):
            found = self.for_dir(posixpath.dirname(d))
        self.cache[d] = found
        return found


def build_index(root: Path, files: list[Path]) -> RepoIndex:
    """`files` 는 검사 대상 파일(절대 경로). 보통 discover() 의 결과다."""
    root = root.resolve()
    rels = sorted({f.resolve().relative_to(root).as_posix() for f in files})
    present = set(rels)
    pkg_dirs = {
        p.parent.relative_to(root).as_posix() for p in root.rglob("package.json") if "node_modules" not in p.parts
    }
    configs = _Configs(root)

    def package_of(rel: str) -> str:
        d = posixpath.dirname(rel) or "."
        while True:
            if d in pkg_dirs or d == ".":
                return d
            d = posixpath.dirname(d) or "."

    def candidates(base: str):
        base = posixpath.normpath(base)
        yield base
        stem = base
        for js in (".js", ".jsx", ".mjs", ".cjs"):
            if base.endswith(js):
                stem = base[: -len(js)]
        for e in EXTS:
            yield stem + e
        for e in EXTS:
            yield posixpath.join(base, "index" + e)

    def resolve(importer: str, spec: str, pkg: str) -> str | None:
        bases: list[str] = []
        if spec.startswith("."):
            bases.append(posixpath.join(posixpath.dirname(importer), spec))
        elif spec.startswith("/"):
            bases.append(spec.lstrip("/"))
        else:
            cfg = configs.for_dir(posixpath.dirname(importer))
            if cfg:
                base_url, paths = cfg
                for pat, targets in paths.items():
                    if pat.endswith("*") and spec.startswith(pat[:-1]):
                        rest = spec[len(pat) - 1 :]
                        bases += [t[:-1] + rest if t.endswith("*") else t for t in targets]
                    elif pat == spec:
                        bases += targets
                if base_url is not None:
                    bases.append(posixpath.join(base_url, spec))
            for alias in ("@/", "~/"):
                if spec.startswith(alias):
                    rest = spec[len(alias) :]
                    p = "" if pkg == "." else pkg
                    bases += [posixpath.join(p, "src", rest), posixpath.join(p, rest)]
        for b in bases:
            for c in candidates(b):
                if c in present:
                    return c
        return None

    roles: dict[str, Role] = {}
    imports: dict[str, set[str]] = {f: set() for f in rels}
    importers: dict[str, set[str]] = {f: set() for f in rels}
    external: dict[str, set[str]] = {}
    unresolved: dict[str, set[str]] = {}
    package = {f: package_of(f) for f in rels}
    for f in rels:
        try:
            with open(root / f, "rb") as fh:
                text = fh.read(READ_BYTES).decode("utf-8", errors="replace")
        except OSError:
            text = ""
        roles[f] = classify(f, text)
        for m in _IMPORT.finditer(text):
            spec = m.group(1) or m.group(2)
            if _ASSET.search(spec):
                continue
            target = resolve(f, spec, package[f])
            if target and target != f:
                imports[f].add(target)
                importers[target].add(f)
            elif target is None:
                local = spec.startswith((".", "/", "@/", "~/"))
                (unresolved if local else external).setdefault(f, set()).add(spec)
    return RepoIndex(root, rels, roles, imports, importers, package, external, unresolved)

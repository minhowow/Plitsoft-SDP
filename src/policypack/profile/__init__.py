"""저장소 프로필: 이 서비스가 하는 일(기능)과 그 기능에 걸릴 수 있는 의무. 모델을 부르지 않는다.

기능은 `features.yaml` 의 신호(package.json 의존성, import 한 꾸러미, 경로 낱말, 글자 그대로의 호출 모양, 화면 파일)로
알아본다. 의무는 `duties.jsonl`(scripts/lawmap_table.py 가 의무 지도에서 만든 표)에서 그 기능에 붙은 것을 싣는다.
여기서는 판단하지 않는다. "이 기능이 있으니 이 의무가 걸릴 수 있다"까지만이다(목록 층).

시험·픽스처·설정 파일(index/roles.py 의 test·config)의 신호는 기능으로 세지 않고 `test_only` 로 따로 낸다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from ruamel.yaml import YAML

from policypack import __version__
from policypack.discover import SKIP_DIRS, discover
from policypack.index.graph import _IMPORT, READ_BYTES
from policypack.index.roles import SERVICE, Role, classify

HERE = Path(__file__).parent
PROFILE_VERSION = 1
EVIDENCE_SHOWN = 5
"""기능마다 싣는 근거 수. 전체 수는 evidence_total 에 있다."""
PLATFORM = {"web-ui", "mobile-app"}
"""화면·앱 자체를 뜻하는 기능. 이것만 있으면 서비스 기능(가입·결제 등)을 찾지 못한 것으로 본다."""
_KIND_ORDER = {"package": 0, "import": 1, "call": 2, "url": 3, "path": 4, "screens": 5}
MOBILE = {"react-native", "expo", "@capacitor/core", "@ionic/react", "@ionic/angular", "@ionic/vue", "cordova"}
WEB = {"next", "nuxt", "vue", "svelte", "@sveltejs/kit", "@angular/core", "gatsby", "@remix-run/react", "astro", "vite",
       "react-scripts", "preact", "solid-js"}  # fmt: skip
"""웹 화면을 만드는 틀. react-dom 은 모바일 앱(Expo 의 웹 지원 등)에도 들어 있어, 모바일 틀이 없을 때만 웹으로 센다."""
SERVER = {"express", "@nestjs/core", "fastify", "koa", "hono", "@hapi/hapi"}
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+")
_QUOTES = "'\"`"


@cache
def load_features() -> dict:
    return YAML(typ="safe").load((HERE / "features.yaml").read_text(encoding="utf-8"))


@cache
def load_duties() -> tuple[dict, ...]:
    lines = (HERE / "duties.jsonl").read_text(encoding="utf-8").splitlines()
    return tuple(json.loads(line) for line in lines if line.strip())


@dataclass(frozen=True)
class Hit:
    feature: str
    kind: str  # package · import · call · path · screens
    value: str
    file: str
    line: int | None
    service: bool

    def record(self) -> dict:
        what = {
            "package": f"package.json 의 dependencies 에 {self.value}",
            "import": f"{self.value} 를 불러옴",
            "call": f"{self.value} 호출",
            "url": f"주소 {self.value}",
            "path": f"경로 낱말 '{self.value}'",
            "screens": "화면 파일(JSX·TSX)",
        }[self.kind]
        return {"file": self.file, "line": self.line, "signal": self.kind, "value": self.value, "what": what}


def code_only(text: str) -> str:
    """JS·TS 글에서 문자열의 내용과 주석을 같은 길이의 빈칸으로 바꾼다(따옴표와 줄바꿈은 남긴다). 템플릿 문자열의
    `${…}` 안은 코드다. 정규식 리터럴과 JSX 글은 따로 알아보지 않는다(드물게 한 줄이 덜 보인다)."""
    out, i, n = list(text), 0, len(text)
    mode: str | None = None  # None 코드 · 따옴표 문자열 · "//" · "/*"
    depth: list[int] = []  # 열린 `${` 마다 그 안의 중괄호 깊이
    while i < n:
        ch = text[i]
        if mode is None:
            if ch in _QUOTES:
                mode = ch
            elif ch == "/" and text[i + 1 : i + 2] in ("/", "*"):
                mode = "//" if text[i + 1] == "/" else "/*"
                out[i] = out[i + 1] = " "
                i += 2
                continue
            elif ch == "{" and depth:
                depth[-1] += 1
            elif ch == "}" and depth:
                if depth[-1] == 0:
                    depth.pop()
                    mode = "`"
                else:
                    depth[-1] -= 1
            i += 1
            continue
        if mode == "//":
            if ch == "\n":
                mode = None
            else:
                out[i] = " "
            i += 1
            continue
        if mode == "/*":
            if text[i : i + 2] == "*/":
                out[i] = out[i + 1] = " "
                mode = None
                i += 2
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        if ch == "\\":
            out[i] = " "
            if i + 1 < n and text[i + 1] != "\n":
                out[i + 1] = " "
            i += 2
            continue
        if mode == "`" and text[i : i + 2] == "${":
            depth.append(0)
            mode = None
            i += 2
            continue
        if ch == mode or (ch == "\n" and mode != "`"):
            mode = None  # 닫는 따옴표, 또는 줄 끝까지 닫히지 않은 따옴표 문자열
        elif ch != "\n":
            out[i] = " "
        i += 1
    return "".join(out)


def path_words(rel: str) -> set[str]:
    """경로를 낱말로 나눈다. 폴더·파일 이름(첫 점 앞)을 대소문자 경계와 부호로 자르고, 붙은 두 낱말을 이은 것도
    넣는다."""
    parts = rel.split("/")
    words: set[str] = set()
    for i, seg in enumerate(parts):
        if i == len(parts) - 1:
            seg = seg.split(".")[0]
        toks = [t.lower() for t in _WORD.findall(seg)]
        words.update(toks)
        words.update(a + b for a, b in zip(toks, toks[1:], strict=False))
    return words


def package_of(spec: str) -> str | None:
    """import 한 이름 → npm 꾸러미 이름. 상대 경로·별칭(@/, ~/)·node: 는 None."""
    if spec.startswith((".", "/", "@/", "~/", "#", "node:")):
        return None
    bits = spec.split("/")
    if spec.startswith("@"):
        return "/".join(bits[:2]) if len(bits) > 1 else None
    return bits[0]


class Matcher:
    def __init__(self, features: list[dict]) -> None:
        self.packages: list[tuple[str, str]] = []  # (이름 또는 '범위/', 기능)
        self.paths: dict[str, list[str]] = {}
        self.calls: dict[str, list[str]] = {}
        self.urls: dict[str, list[str]] = {}
        self.screens: list[str] = []
        for f in features:
            sig = f.get("signals") or {}
            self.packages += [(p, f["id"]) for p in sig.get("packages") or []]
            for w in sig.get("paths") or []:
                self.paths.setdefault(w, []).append(f["id"])
            for c in sig.get("calls") or []:
                self.calls.setdefault(c, []).append(f["id"])
            for u in sig.get("urls") or []:
                self.urls.setdefault(u, []).append(f["id"])
            if sig.get("screens"):
                self.screens.append(f["id"])
        alts = [
            re.escape(c) + (r"(?![\w$])" if re.match(r"[\w$]", c[-1]) else "")
            for c in sorted(self.calls, key=len, reverse=True)
        ]
        self.call_re = re.compile(r"(?<![\w$])(?:" + "|".join(alts) + ")") if alts else None
        # 주소는 문자열이 그 주소로 시작할 때만 센다(fetch("https://api.openai.com/…")). 문장 속 주소는 아니다
        hosts = [
            (re.escape(u) if u.endswith("://") else r"(?:https?://|wss?://)?" + re.escape(u))
            for u in sorted(self.urls, key=len, reverse=True)
        ]
        self.url_re = re.compile(r"(?<=[\"'`])(" + "|".join(hosts) + ")") if hosts else None

    def url_of(self, matched: str) -> str:
        return next(u for u in sorted(self.urls, key=len, reverse=True) if matched.endswith(u) or matched == u)

    def package_features(self, name: str) -> list[str]:
        return [f for p, f in self.packages if name == p or (p.endswith("/") and name.startswith(p))]


def _line_of(text: str, needle: str) -> int | None:
    k = text.find(needle)
    return text.count("\n", 0, k) + 1 if k >= 0 else None


def _package_jsons(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if "package.json" in filenames:
            yield Path(dirpath) / "package.json"


def scan(root: Path, m: Matcher) -> tuple[list[Hit], dict, dict]:
    """(신호, 파일 수, 플랫폼을 가를 사실). 사실은 서비스 package.json 의 모든 의존성(dev 포함)과 서버 파일 수다."""
    hits: list[Hit] = []
    counts = {"source": 0, "service": 0, "test_or_config": 0, "package_json": 0}
    facts: dict = {"deps": set(), "server_files": 0}

    for pj in sorted(_package_jsons(root)):
        rel = pj.relative_to(root).as_posix()
        try:
            text = pj.read_text(encoding="utf-8")
            doc = json.loads(text)
            deps = doc.get("dependencies") or {}
        except (OSError, ValueError, AttributeError):
            continue
        counts["package_json"] += 1
        service = classify(rel, text) in SERVICE
        if service:
            for key in ("dependencies", "devDependencies"):
                if isinstance(doc.get(key), dict):
                    facts["deps"] |= set(doc[key])
        for name in deps if isinstance(deps, dict) else []:
            for feat in m.package_features(name):
                hits.append(Hit(feat, "package", name, rel, _line_of(text, f'"{name}"'), service))

    for path in discover([root], ["javascript", "typescript"]).files:
        rel = path.relative_to(root).as_posix()
        try:
            with open(path, "rb") as fh:
                text = fh.read(READ_BYTES).decode("utf-8", errors="replace")
        except OSError:
            continue
        role = classify(rel, text)
        service = role in SERVICE
        facts["server_files"] += role is Role.SERVER
        counts["source"] += 1
        counts["service" if service else "test_or_config"] += 1
        if role is Role.SCREEN:
            hits += [Hit(f, "screens", "screen", rel, None, service) for f in m.screens]
        for w in sorted(path_words(rel) & m.paths.keys()):
            hits += [Hit(f, "path", w, rel, None, service) for f in m.paths[w]]
        for mt in _IMPORT.finditer(text):
            name = package_of(mt.group(1) or mt.group(2))
            if name:
                line = text.count("\n", 0, mt.start()) + 1
                hits += [Hit(f, "import", name, rel, line, service) for f in m.package_features(name)]
        code = code_only(text)
        if m.call_re:
            # 호출 모양은 문자열·주석 밖의 코드에서만 센다(웹 저장소의 사례 글 속 'openai.responses.create' 가 잡혔다)
            for mt in m.call_re.finditer(code):
                line = code.count("\n", 0, mt.start()) + 1
                hits += [Hit(f, "call", mt.group(0), rel, line, service) for f in m.calls[mt.group(0)]]
        if m.url_re:
            for mt in m.url_re.finditer(text):
                if code[mt.start() - 1] not in _QUOTES:  # 주석 안이다(주석은 따옴표까지 지운다)
                    continue
                url, line = m.url_of(mt.group(1)), text.count("\n", 0, mt.start()) + 1
                hits += [Hit(f, "url", url, rel, line, service) for f in m.urls[url]]
    return hits, counts, facts


def platforms(facts: dict, counts: dict, screens: bool) -> list[str]:
    """web · mobile · server. 모바일 앱 틀이 있으면 웹 화면 틀(next·vite 등)이 따로 있을 때만 웹이다.
    package.json 이 없는데 화면 파일이 있으면 웹으로 본다."""
    deps = facts["deps"]
    mobile = bool(deps & MOBILE)
    web = bool(deps & WEB) or ("react-dom" in deps and not mobile) or (screens and not counts["package_json"])
    server = bool(deps & SERVER) or facts["server_files"] > 0
    return [p for p, on in (("web", web), ("mobile", mobile), ("server", server)) if on]


def _duty_item(d: dict) -> dict:
    return {
        "id": d["id"],
        "law": d["law"],
        "article": d["article"],
        "title": d["title"],
        "duty": d["duty"],
        "url": d["url"],
        "review_candidate": d["review_candidate"],
        "quote_check": d["quote_check"],
    }


def _duty_block(duties: list[dict]) -> dict:
    return {
        "count": len(duties),
        "review_candidates": sum(d["review_candidate"] for d in duties),
        "items": [_duty_item(d) for d in duties],
    }


def _evidence(hits: list[Hit]) -> list[dict]:
    """기능 하나의 근거. 같은 신호(종류·값)는 한 번만 싣고, 꾸러미·호출처럼 뜻이 분명한 것을 앞에 둔다."""
    seen, out = set(), []
    for h in sorted(hits, key=lambda h: (_KIND_ORDER[h.kind], h.file, h.line or 0)):
        key = (h.kind, h.value) if h.kind != "screens" else (h.kind, h.file)
        if key not in seen:
            seen.add(key)
            out.append(h.record())
    return out


def profile(root: Path) -> dict:
    spec = load_features()
    features = spec["features"]
    hits, counts, facts = scan(root, Matcher(features))
    plats = platforms(facts, counts, any(h.kind == "screens" and h.service for h in hits))
    if "web" not in plats:
        # 웹이 아니면 화면 파일은 웹 화면 신호가 아니다(React Native 앱에 웹 접근성을 묻지 않는다)
        hits = [h for h in hits if h.kind != "screens"]
    by_feature: dict[str, list[Hit]] = {}
    for h in hits:
        by_feature.setdefault(h.feature, []).append(h)
    duties = load_duties()

    found, test_only = [], []
    for f in features:
        fh = by_feature.get(f["id"], [])
        service_hits = [h for h in fh if h.service]
        if service_hits:
            ev = _evidence(service_hits)
            mine = [d for d in duties if d["feature"] == f["id"]]
            found.append(
                {
                    "id": f["id"],
                    "name": f["name"],
                    "evidence": ev[:EVIDENCE_SHOWN],
                    "evidence_total": len(ev),
                    "duties": _duty_block(mine),
                }
            )
        elif fh:
            ev = _evidence(fh)
            test_only.append(
                {"id": f["id"], "name": f["name"], "evidence": ev[:EVIDENCE_SHOWN], "evidence_total": len(ev)}
            )

    service_features = [f for f in found if f["id"] not in PLATFORM]
    out = {
        "profile_version": PROFILE_VERSION,
        "tool": {"name": "policypack", "version": __version__},
        "files": counts,
        "platforms": plats,
        "service_features": len(service_features),
        "features": found,
    }
    if service_features:
        common = [d for d in duties if d["feature"] == "common"]
        out["common"] = {"name": spec["common"]["name"], "duties": _duty_block(common)}
    else:
        out["note"] = (
            "서비스 기능(가입·결제·위치·AI 호출 등)을 하나도 찾지 못했습니다. "
            + ("화면 파일은 있습니다. " if found else "")
            + "라이브러리·예제·문서 저장소이거나, 이 도구가 아직 알아보지 못하는 모양일 수 있습니다."
        )
    status = [d for d in duties if d["feature"] == "status"]
    out["status"] = {
        "name": spec["status"]["name"],
        "count": len(status),
        "note": "공공기관·금융회사 등 운영 주체의 지위로 걸리는 의무입니다. 코드로 가리지 않아 목록에 싣지 않습니다.",
    }
    out["test_only"] = test_only
    listed = sum(f["duties"]["count"] for f in found) + (out["common"]["duties"]["count"] if "common" in out else 0)
    review = sum(f["duties"]["review_candidates"] for f in found) + (
        out["common"]["duties"]["review_candidates"] if "common" in out else 0
    )
    out["totals"] = {"features": len(found), "duties": listed, "review_candidates": review}
    return out

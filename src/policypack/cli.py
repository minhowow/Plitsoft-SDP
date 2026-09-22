"""명령줄 진입점.

종료 코드는 ESLint·Ruff·Semgrep 규약을 따른다.
  0  검토 필요 없음 / 통과
  1  검토 필요가 하나 이상
  2  도구 오류

`test` 도 같은 규약이다. 0 통과 · 1 실패(`--strict` 면 커버리지 빈틈까지) · 2 도구 오류.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path

from policypack import __version__
from policypack.defaults import default_pack
from policypack.discover import Discovery
from policypack.errors import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, ConfigError, PackError, PolicypackError
from policypack.pack.loader import (
    check_legal_texts,
    check_review_dates,
    find_anchor_without_regions,
    find_unconfirmable_weak,
    load_pack,
    pack_digest,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"

#: 파일명 → (모델, 제목). schema --write/--check 가 전부 다룬다.
SCHEMAS = {
    "policy-pack-0.3.json": ("policypack.model:PolicyPack", "정책 팩 v0.3"),
    "policy-test-0.1.json": ("policypack.packtest:PolicyTestFile", "정책 테스트 v0.1"),
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="policypack", description="국내 법·정책 관점 코드 검토")
    p.add_argument("--version", action="version", version=f"policypack {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<명령>")

    v = sub.add_parser("validate", help="정책 팩이 문법에 맞는지 보고, 미완인 곳을 드러낸다")
    v.add_argument("pack", nargs="?", default=None, help="기본: 내장 kr-core 팩")
    v.add_argument("--strict", action="store_true", help="경고도 실패로 센다")

    s = sub.add_parser("schema", help="정책 팩·테스트 파일의 JSON Schema 를 만들거나 대조한다")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="schemas/ 에 다시 쓴다")
    g.add_argument("--check", action="store_true", help="커밋된 것과 다르면 실패한다")

    d = sub.add_parser("doctor", help="정적 백엔드(semgrep)와 기본 정책 팩 경로를 점검한다")
    d.add_argument("--json", action="store_true")

    sc = sub.add_parser("scan", help="코드를 검사한다")
    sc.add_argument(
        "paths",
        nargs="*",
        help="검사할 파일·폴더 (기본: 현재 폴더). --staged·--diff 와 함께 주면 그 아래로 좁힌다. "
        "그때 경로를 안 주면 저장소 전체다",
    )
    sc.add_argument("--config", default=None, help="정책 팩 경로 (기본: 내장 kr-core 팩)")
    scope = sc.add_mutually_exclusive_group()
    scope.add_argument("--staged", action="store_true", help="스테이징된 파일만 검사한다")
    scope.add_argument(
        "--diff",
        metavar="REF",
        help="REF 와의 분기점 이후 바뀐 파일만 검사한다. 커밋 안 한 변경·새 파일도 넣는다 (예: origin/main)",
    )
    sc.add_argument(
        "--judge",
        default="none",
        help="정적으로 결론이 안 난 곳을 물을 AI 판정자: none(기본) | claude-cli:<모델> | anthropic:<모델>",
    )
    sc.add_argument("--output-format", default="full", choices=["full", "concise", "json", "sarif"])
    sc.add_argument(
        "--fail-on", default="uncertain", choices=["review", "uncertain", "never"], help="무엇까지를 종료 코드 1로 볼지"
    )
    sc.add_argument("--exit-zero", action="store_true", help="검토할 것이 있어도 0으로 끝낸다")
    sc.add_argument("--explain", action="store_true", help="판정 경로를 함께 낸다")
    sc.add_argument("--no-color", action="store_true")

    t = sub.add_parser("test", help="정책 팩의 픽스처로 기대 판정을 확인한다 (모델 호출 0회)")
    t.add_argument("paths", nargs="*", help="팩 디렉터리·tests·*.test.yaml 경로 (기본: 내장 팩의 tests)")
    t.add_argument("--config", default=None, help="정책 팩 경로 (기본: 경로 안의 팩, 없으면 내장 kr-core)")
    t.add_argument("--output-format", default="text", choices=["text", "json"])
    t.add_argument("--strict", action="store_true", help="커버리지 빈틈도 실패로 센다")
    t.add_argument("--exit-zero", action="store_true", help="실패가 있어도 0으로 끝낸다")
    t.add_argument("--explain", action="store_true", help="통과한 픽스처의 판정 경로도 낸다")
    t.add_argument("--no-color", action="store_true")
    return p


# ── validate ────────────────────────────────────────────────────────────────


def cmd_validate(args) -> int:
    base = Path(args.pack) if args.pack else default_pack()
    pack = load_pack(base)
    if base.is_file():
        base = base.parent

    n_rules = sum(1 for _ in pack.iter_rules())
    n_static = sum(
        1 for _, r in pack.iter_rules() for p in list(r.applies_when) + list(r.compliant_if_any) if not p.is_ai
    )
    n_ai = sum(1 for _, r in pack.iter_rules() for p in r.compliant_if_any if p.is_ai) + sum(
        1 for _, r in pack.iter_rules() if r.applies_ai
    )
    print(f"{pack.pack.title} ({pack.pack.id})  해시 {pack_digest(base)}")
    print(f"  정책 {len(pack.policies)} · 규칙 {n_rules} · 정적 조건 {n_static} · AI 질문 {n_ai}")

    groups = [
        ("조문 추적성", check_legal_texts(pack, base)),
        ("재검토 기한", check_review_dates(pack)),
        ("함수 단위로 판정할 수 없는 언어", find_anchor_without_regions(pack)),
        ("확인할 수 없는 약한 대안", find_unconfirmable_weak(pack)),
    ]
    total = 0
    for title, warns in groups:
        if not warns:
            continue
        total += len(warns)
        print(f"\n  {title} ({len(warns)}건)")
        for w in warns:
            print(f"    - {w}")

    print()
    if total == 0:
        print("문법에 맞고, 미완인 곳도 없습니다.")
        return EXIT_OK
    print(f"문법에는 맞습니다. 다만 경고 {total}건이 있습니다.")
    if args.strict:
        print("--strict 라서 실패로 처리합니다.")
        return EXIT_FINDINGS
    return EXIT_OK


# ── schema ──────────────────────────────────────────────────────────────────


def _schema_text(dotted: str, title: str) -> str:
    module, name = dotted.split(":")
    model = getattr(import_module(module), name)
    schema = model.model_json_schema(by_alias=True, mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = title
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def cmd_schema(args) -> int:
    # 스키마는 소스 저장소의 schemas/ 에 커밋하는 개발용 산출물이다. 설치본에서 돌리면 SCHEMA_DIR 가 엉뚱한
    # 곳(site-packages 의 부모)을 가리켜, 거기 만들거나 지우게 된다
    if not (SCHEMA_DIR.parent / "pyproject.toml").is_file() or not (SCHEMA_DIR.parent / "src" / "policypack").is_dir():
        raise ConfigError("schema 는 policypack 소스 저장소에서만 씁니다")
    stale = []
    for filename, (dotted, title) in SCHEMAS.items():
        text = _schema_text(dotted, title)
        target = SCHEMA_DIR / filename
        if args.write:
            SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"썼습니다: schemas/{filename} ({len(text):,} bytes)")
        elif not target.exists() or target.read_text(encoding="utf-8") != text:
            stale.append(filename)
    # schemas/ 는 이 명령이 만든다. 모델에 없는 파일(판본을 올리기 전의 옛 스키마 등)이 남으면 편집기가
    # 낡은 문법으로 검사하므로 --write 는 지우고 --check 는 실패한다
    orphans = (
        sorted(p for p in SCHEMA_DIR.glob("policy-*.json") if p.name not in SCHEMAS) if SCHEMA_DIR.is_dir() else []
    )
    if args.write:
        for p in orphans:
            p.unlink()
            print(f"지웠습니다: schemas/{p.name} (모델에 없음)")
        return EXIT_OK
    if stale or orphans:
        why = [f"모델과 어긋남: {', '.join(stale)}"] if stale else []
        why += [f"모델에 없음: {', '.join(p.name for p in orphans)}"] if orphans else []
        print(
            f"오류: 커밋된 스키마가 모델과 맞지 않습니다({' · '.join(why)}).\n"
            "policypack schema --write 로 다시 만드세요.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    print(f"schemas/ {len(SCHEMAS)}개가 모델과 일치합니다.")
    return EXIT_OK


# ── doctor ──────────────────────────────────────────────────────────────────


def cmd_doctor(args) -> int:
    from policypack.static.semgrep_cli import diagnose

    info = diagnose()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print("정적 백엔드")
        print(f"  실행 파일 : {info['path'] or '찾지 못함'}")
        print(f"  버전      : {info['version'] or '-'}")
        print(f"  고른 이유 : {info['source']}")
        print("기본 경로")
        print(f"  정책 팩   : {default_pack()}")
        if info["notes"]:
            for n in info["notes"]:
                print(f"  ! {n}")
    return EXIT_OK if info["path"] else EXIT_ERROR


# ── scan ────────────────────────────────────────────────────────────────────


@dataclass
class Selection:
    found: Discovery
    note: str = ""
    root: Path = field(default_factory=Path.cwd)
    """보고 경로의 기준. 범위 검사면 저장소 루트다. 하위 폴더에서 돌려도 SARIF uri 와 지문이 같아야 한다."""


#: 판정자에게 코드를 보내는 곳. 판정 규칙이 하나라 범위도 하나다(evaluate/planner.py).
_EGRESS_SCOPE = (
    "규칙이 적용되는데 강한 정적 대안으로 준수가 확인되지 않은 파일(이름·정규식 같은 약한 근거로만 준수가 보이는 "
    "파일 포함)과, 적용 여부가 정적으로 정해지지 않아 적용 질문(applies-ai)을 묻는 파일"
)

#: 판정자 CLI·SDK 가 따르는 사용자 설정 가운데 코드의 목적지를 바꾸거나 늘리는 것.
#: 끊지는 않는다 — 사내 게이트웨이가 필수 경로인 사용자도 있다. 대신 실제 목적지를 알린다.
_ROUTING_VARS = ("ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
_TELEMETRY_VARS = ("CLAUDE_CODE_ENABLE_TELEMETRY", "OTEL_LOG_USER_PROMPTS", "OTEL_EXPORTER_OTLP_ENDPOINT")


def _egress_notice(spec: str, env: dict | None = None) -> str:
    """AI 판정자를 켰을 때 무엇이 어디로 나가는지 알린다.

    이 도구에서 코드가 기계 밖으로 나가는 경로는 이것 하나다. 실행할 때마다 정확한 범위를 알린다.
    """
    from policypack.discover import MAX_BYTES
    from policypack.evaluate import engine

    env = os.environ if env is None else env
    lines = [
        f"알림: AI 판정자 {spec} 를 씁니다. {_EGRESS_SCOPE}의 코드가 판정자에게 전송됩니다.",
        f"      파일 단위 규칙: 파일의 전체 내용({MAX_BYTES // 1_000_000}MB 미만).",
        "      함수 단위 규칙(scope: anchor): 앵커를 감싼 함수와, 같은 파일에서 그 함수가 쓰는 최상위 선언"
        f"(각 {engine.DECL_MAX_LINES}줄까지)·import, 그 함수를 부르는 줄(이름 없는 콜백이면 같은 문장의 앞줄 "
        f"{engine.STATEMENT_HEAD_MAX_LINES}줄까지), 그 함수가 읽는 this 필드에 값을 넣는 줄"
        f"(합쳐 {engine.HEADER_MAX_LINES}줄·{engine.HEADER_MAX_CHARS}자까지). 앵커가 함수 밖에만 있거나 함수 경계를"
        " 얻지 못한 파일과 적용 여부를 AI에 묻는 질문은 파일 전체가, 함수 안팎에 앵커가 섞인 파일의 함수 밖"
        " 판정은 함수 본문을 비운 모듈 최상위 줄이 갑니다.",
    ]
    routing = [f"{k}={env[k]}" for k in _ROUTING_VARS if env.get(k)]
    if routing:
        lines.append(f"      판정자가 따르는 설정 때문에 실제 목적지가 바뀝니다: {', '.join(routing)}")
    telemetry = [k for k in _TELEMETRY_VARS if env.get(k)]
    if telemetry and spec.startswith("claude-cli"):
        lines.append(
            f"      텔레메트리 설정({', '.join(telemetry)})이 있어 판정자 CLI 가 그 수집기에도 기록을 보낼 수 있습니다."
        )
    return "\n".join(lines)


def _warn_engine_errors(engine: str, errors: list[str]) -> None:
    """어느 파일인지 모르는 엔진 오류. 보고서에도 싣지만 CI 로그에 남게 stderr 에도 알린다."""
    if errors:
        print(
            f"경고: {engine or '정적 엔진'} 이 어느 파일인지 밝히지 않은 오류 {len(errors)}건을 냈습니다"
            f"({errors[0][:120]}). 그 실행의 대상 파일은 모든 정적 조건을 '모름'으로 둡니다.",
            file=sys.stderr,
        )


def _skip_note(counts: dict[str, int]) -> str:
    labels = {
        "big": "1MB 초과",
        "dir": "생성물 디렉터리",
        "gen": "축소·번들 파일",
        "link": "심볼릭 링크",
        "unreadable": "읽을 수 없는 파일",
        "engine": "엔진이 읽지 못하는 확장자(.mts·.cts·대문자 등)",
    }
    parts = [f"{labels[k]} {n}개" for k, n in counts.items() if n and k in labels]
    return f" ({' · '.join(parts)} 건너뜀)" if parts else ""


def _scope_start(paths: list[Path]) -> Path:
    """범위 검사를 할 저장소. 경로 인자가 있으면 **그 경로의** 저장소다.

    cwd 의 저장소로 정하면, 다른 저장소나 중첩 저장소를 가리켜 돌렸을 때 그쪽 변경을
    하나도 못 보고 "검사할 파일이 없습니다"로 통과한다.
    """
    from policypack import gitscope

    if not paths:
        return Path.cwd()
    roots = set()
    for p in paths:
        if not p.exists():
            raise ConfigError(f"경로가 없습니다: {p}")
        roots.add(gitscope.repo_root(p if p.is_dir() else p.parent))
    if len(roots) > 1:
        names = ", ".join(sorted(map(str, roots)))
        raise ConfigError(f"경로들이 서로 다른 git 저장소에 있습니다: {names}. 한 번에 하나씩 돌리세요.")
    return roots.pop()


def _select_targets(args, languages: list[str]) -> Selection:
    """무엇을 판정할지.

    범위 검사(`--staged`·`--diff`)도 전체 검사와 같은 규칙(`admit`)으로 파일을 거른다. 같은 파일의 판정이
    어떻게 돌렸느냐에 따라 달라지면 안 된다.
    """
    from policypack import gitscope
    from policypack.discover import admit, discover, extensions_for

    paths = [Path(p) for p in (args.paths or [])]
    missing = [p for p in paths if not p.exists()]
    if missing:
        # CI 에서 경로를 오타내면 "검사할 파일이 없습니다"로 조용히 통과했다
        raise ConfigError(f"경로가 없습니다: {', '.join(map(str, missing))}")
    if not (args.staged or args.diff):
        found = discover(paths or [Path(".")], languages)
        notes = []
        if found.skipped_links:
            notes.append(f"심볼릭 링크 {found.skipped_links}개는 건너뜁니다. 가리키는 파일을 직접 지정하세요.")
        if found.skipped_generated:
            # 말없이 빼지 않는다. 이 모듈이 semgrep 의 자체 필터를 쓰지 않는 이유와 같다.
            notes.append(f"축소·번들 파일 {len(found.skipped_generated)}개는 건너뜁니다. 원본을 검사하세요.")
        if found.skipped_unreadable:
            names = ", ".join(str(p) for p in found.skipped_unreadable[:3])
            notes.append(f"읽을 권한이 없는 파일 {len(found.skipped_unreadable)}개는 건너뜁니다({names}).")
        if found.skipped_engine:
            names = ", ".join(str(p) for p in found.skipped_engine[:3])
            notes.append(
                f"Semgrep 이 읽지 못하는 철자의 파일(.mts·.cts·대문자 확장자 등) {len(found.skipped_engine)}개는 "
                f"검사하지 않았습니다({names})."
            )
        return Selection(found=found, note="\n".join(notes))

    start = _scope_start(paths)
    scope = gitscope.staged(start) if args.staged else gitscope.changed_since(start, args.diff)
    files = gitscope.within(scope.files, paths) if paths else list(scope.files)

    exts = extensions_for(languages)
    named = {p.resolve() for p in paths if p.is_file()}  # 사용자가 이름을 댄 파일은 확장자를 묻지 않는다
    found = Discovery()
    counts: dict[str, int] = {}
    for f in files:
        verdict = admit(f, scope.root, exts | ({f.suffix.lower()} if f.resolve() in named else set()))
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict == "ok":
            found.files.append(f)
        elif verdict == "big":
            found.skipped_big.append(f)
        elif verdict == "gen":
            found.skipped_generated.append(f)
        elif verdict == "unreadable":
            found.skipped_unreadable.append(f)
        elif verdict == "engine":
            found.skipped_engine.append(f)
    found.files.sort()
    found.skipped_links = counts.get("link", 0)

    note = f"{scope.label} {len(found.files)}개를 검사합니다{_skip_note(counts)}."
    if scope.dirty:
        names = ", ".join(str(p.relative_to(scope.root)) for p in scope.dirty[:3])
        note += (
            f"\n  주의: 스테이징한 뒤 또 바뀐 파일이 있습니다({names}). 작업 트리를 검사하므로 "
            f"커밋될 내용과 다를 수 있습니다. pre-commit 으로 돌리면 이 문제가 없습니다."
        )
    return Selection(found=found, note=note, root=scope.root)


def _scan_languages(pack) -> list[str]:
    """파일을 고를 언어. 팩의 기본 언어와 규칙마다 적은 언어의 합이다."""
    langs = set(pack.defaults.languages)
    for _, rule in pack.iter_rules():
        langs |= set(pack.languages_for(rule))
    return sorted(langs)


def cmd_scan(args) -> int:
    from policypack.discover import language_of
    from policypack.evaluate.engine import EvalResult, Target, evaluate
    from policypack.report.outcome import Outcome
    from policypack.static.compile import compile_static
    from policypack.static.semgrep_cli import SemgrepBackend

    base = Path(args.config) if args.config else default_pack()
    pack = load_pack(base)
    if base.is_file():
        base = base.parent
    digest = pack_digest(base)

    sel = _select_targets(args, _scan_languages(pack))
    found, root = sel.found, sel.root
    if sel.note:
        print(sel.note, file=sys.stderr)
    # 판정자는 파일이 없어도 같은 방식으로 정한다. 빈 보고서의 judge 가 보통 보고서와 같게, 잘못된 --judge 는
    # 파일이 없어도 오류로 알린다
    judge = None
    if args.judge != "none":
        from policypack.judge.anthropic_api import build as build_judge
        from policypack.judge.anthropic_api import preflight

        try:
            judge = build_judge(args.judge)
        except ValueError as e:
            raise ConfigError(f"{e}. 쓸 수 있는 것: none · claude-cli:<모델> · anthropic:<모델>") from e
        problem = preflight(args.judge)
        if problem:
            raise ConfigError(problem)
        if found.files:
            print(_egress_notice(args.judge), file=sys.stderr)

    if not found.files:
        print("검사할 파일이 없습니다.", file=sys.stderr)
        if args.output_format in ("json", "sarif"):
            # CI 가 SARIF 를 올리는 단계는 빈 stdout 을 받으면 실패한다. 빈 보고서를 낸다.
            empty = EvalResult(
                judge_id=getattr(judge, "id", "") if judge else "",
                skipped=[str(p) for p in found.skipped_files()],
            )
            _emit(args, empty, pack, base, root, digest, n_files=0)
        return EXIT_OK

    targets = [Target(path=f, lang=language_of(f)) for f in found.files]
    static = SemgrepBackend().run(compile_static(pack), [t.path for t in targets])
    if static.rule_errors:
        raise PackError("정책 팩의 정적 조건이 잘못됐습니다:\n  " + "\n  ".join(static.rule_errors))
    _warn_engine_errors(static.engine, static.unlocated_errors)

    # 판정자가 없거나 답하지 못하면 AI 에게 물어야 했던 곳을 보고서가 'AI 확인 필요'로 알린다(요약 줄·JSON·SARIF).
    result = evaluate(pack, targets, static, judge=judge)
    result.skipped = [str(p) for p in found.skipped_files()]

    _emit(args, result, pack, base, root, digest, n_files=len(found))

    if args.exit_zero or args.fail_on == "never":
        return EXIT_OK
    if args.fail_on == "review":
        hit = any(f.outcome is Outcome.NEEDS_REVIEW for f in result.findings)
    else:
        hit = any(f.outcome.is_finding for f in result.findings)
    return EXIT_FINDINGS if hit else EXIT_OK


def _emit(args, result, pack, base, root, digest, n_files: int) -> None:
    from policypack.report import json_out, sarif, text

    if args.output_format == "json":
        print(json_out.dumps(result, root, digest, {"files": n_files}))
    elif args.output_format == "sarif":
        print(sarif.dumps(result, pack, base, root, digest))
    else:
        color = False if args.no_color else None
        print(text.render(result, root, explain=args.explain or args.output_format == "full", color=color))


# ── test ────────────────────────────────────────────────────────────────────


def _owning_pack(p: Path) -> Path | None:
    p = p.resolve()
    for d in ([p] if p.is_dir() else []) + list(p.parents):
        if (d / "pack.yaml").is_file():
            return d
    return None


def cmd_test(args) -> int:
    from policypack import packtest
    from policypack.report import testrun
    from policypack.static.semgrep_cli import SemgrepBackend

    paths = [Path(p) for p in args.paths]
    # 경로가 속한 팩을 위로 올라가며 찾는다. <팩>/tests 나 그 안의 *.test.yaml 을 주면 그 팩이다.
    # 경로 자신만 보면 내장 kr-core 로 시험해서 엉뚱한 팩의 결과가 나온다.
    packs = sorted({d for p in paths if (d := _owning_pack(p)) is not None})
    if len(packs) > 1:
        raise ConfigError(f"한 번에 팩 하나만 시험합니다: {', '.join(map(str, packs))}")
    if args.config:
        base = Path(args.config)
        if base.is_file():
            base = base.parent
        if packs and base.resolve() != packs[0]:
            raise ConfigError(f"--config({base}) 와 경로의 팩({packs[0]})이 다릅니다")
    else:
        base = packs[0] if packs else default_pack()
    pack = load_pack(base)

    fixtures = packtest.collect(paths or [base], pack)
    if not fixtures:
        raise ConfigError(f"픽스처가 없습니다: {', '.join(map(str, paths or [base / 'tests']))}")

    # 커버리지를 셀 범위. 팩 전체(경로 없음·팩 디렉터리·tests 뿌리)면 모든 규칙, 테스트 파일 몇 개면
    # 그 파일들이 기대를 적은 규칙만. 다른 정책의 빈틈으로 --strict 가 실패하면 안 된다
    whole = not paths or any(p.resolve() in (base.resolve(), (base / "tests").resolve()) for p in paths)
    scope = None if whole else {ref for f in fixtures for ref in f.expects}

    run = packtest.run(pack, fixtures, SemgrepBackend(), coverage_scope=scope)
    _warn_engine_errors(run.engine, run.engine_errors)
    root = Path.cwd()
    if args.output_format == "json":
        print(testrun.dumps(run, root, pack.pack.id, pack_digest(base)))
    else:
        color = False if args.no_color else None
        print(testrun.render(run, root, explain=args.explain, color=color, pack_path=base))

    if args.exit_zero:
        return EXIT_OK
    return EXIT_FINDINGS if run.failed or (args.strict and (run.gaps or run.unused_stubs)) else EXIT_OK


COMMANDS = {
    "scan": cmd_scan,
    "validate": cmd_validate,
    "schema": cmd_schema,
    "doctor": cmd_doctor,
    "test": cmd_test,
}


def _sigterm_exits():
    """SIGTERM 을 정상 종료로 바꾼다. 기본 SIGTERM 은 finally 와 atexit 를 돌리지 않아, CI 취소나
    `timeout` 으로 끝날 때마다 설정 임시 파일과 semgrep 상태 디렉터리가 남았다(실측). 주 스레드에서만
    걸 수 있다. 원래 처리기를 돌려준다."""
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return None
    return signal.signal(signal.SIGTERM, lambda signum, _frame: sys.exit(128 + signum))


def main(argv: list[str] | None = None) -> int:
    previous = _sigterm_exits()
    try:
        return _main(argv)
    finally:
        if previous is not None:
            import signal

            signal.signal(signal.SIGTERM, previous)


def _main(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_ERROR
    try:
        return COMMANDS[args.command](args)
    except PolicypackError as e:
        print(f"오류: {e}", file=sys.stderr)
        return e.exit_code
    except Exception:  # noqa: BLE001
        # 처리하지 못한 예외로 파이썬이 1로 끝나면 CI 는 "검토할 것이 있다"로 읽는다. 도구 오류는 2다.
        traceback.print_exc()
        print("오류: policypack 내부 오류입니다. 위 내용을 붙여 알려 주세요.", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

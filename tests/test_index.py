"""저장소 색인: 파일 역할, import 풀기, 함께 볼 파일."""

from __future__ import annotations

from pathlib import Path

import pytest

from policypack.index import Role, build_index, classify


def write(root: Path, files: dict[str, str]) -> list[Path]:
    out = []
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        out.append(p)
    return out


@pytest.mark.parametrize(
    ("rel", "text", "role"),
    [
        ("src/a.test.ts", "expect(1)", Role.TEST),
        ("src/__tests__/b.tsx", "return (<div/>)", Role.TEST),
        ("src/Button.stories.tsx", "<Button/>", Role.TEST),
        ("next.config.js", "module.exports = {}", Role.CONFIG),
        (".eslintrc.cjs", "module.exports = {}", Role.CONFIG),
        ("pages/api/chat.ts", "export default function handler(req, res) {}", Role.SERVER),
        ("app/api/chat/route.ts", "export async function POST(req) {}", Role.SERVER),
        ("src/actions.ts", "'use server'\nexport async function save() {}", Role.SERVER),
        ("server/index.js", "const app = express();", Role.SERVER),
        ("src/pages/Signup.tsx", "export default function S() { return (<form/>) }", Role.SCREEN),
        ("src/components/Chat.jsx", "const C = () => <div>hi</div>", Role.SCREEN),
        ("src/utils/date.ts", "export const f = () => 1", Role.OTHER),
        ("src/api/client.ts", "export const get = () => fetch('/x')", Role.OTHER),
    ],
)
def test_roles(rel, text, role):
    assert classify(rel, text) is role


def test_imports_resolve_relative_alias_and_index(tmp_path):
    files = write(
        tmp_path,
        {
            "package.json": "{}",
            "tsconfig.json": '{ // 주석\n "compilerOptions": {"baseUrl": ".", "paths": {"@app/*": ["src/*"],},} }',
            "src/pages/Signup.tsx": (
                "import { Agree } from '../components/Agree'\n"
                "import type { U } from '@app/types'\n"
                "import api from '@/lib/api'\n"
                "import {\n  x,\n  y,\n} from './helpers.js'\n"
                "const z = require('lodash')\n"
                "export default function S() { return (<form/>) }\n"
            ),
            "src/pages/helpers.ts": "export const x = 1, y = 2",
            "src/components/Agree/index.tsx": "export const Agree = () => <input type='checkbox'/>",
            "src/types.ts": "export type U = {}",
            "src/lib/api.ts": "import './missing'\nexport default {}",
        },
    )
    idx = build_index(tmp_path, [f for f in files if f.suffix in (".ts", ".tsx")])
    assert idx.imports["src/pages/Signup.tsx"] == {
        "src/components/Agree/index.tsx",
        "src/types.ts",
        "src/lib/api.ts",
        "src/pages/helpers.ts",
    }
    assert idx.importers["src/types.ts"] == {"src/pages/Signup.tsx"}
    assert idx.external["src/pages/Signup.tsx"] == {"lodash"}
    assert idx.unresolved["src/lib/api.ts"] == {"./missing"}
    assert idx.summary()["edges"] == 4


def test_tsconfig_extends_and_monorepo_packages(tmp_path):
    files = write(
        tmp_path,
        {
            "package.json": "{}",
            "tsconfig.base.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@ui/*": ["packages/ui/src/*"]}}}',
            "apps/web/package.json": "{}",
            "apps/web/tsconfig.json": '{"extends": "../../tsconfig.base.json"}',
            "apps/web/src/page.tsx": "import { B } from '@ui/Button'\nexport default () => <B/>",
            "apps/web/src/terms/page.tsx": "export default () => <p>약관</p>",
            "apps/web/src/app/layout.tsx": "export default ({children}) => <body>{children}</body>",
            "packages/ui/package.json": "{}",
            "packages/ui/src/Button.tsx": "export const B = () => <button/>",
            "packages/ui/src/privacy.tsx": "export const P = () => <p/>",
        },
    )
    idx = build_index(tmp_path, [f for f in files if f.suffix == ".tsx"])
    assert idx.imports["apps/web/src/page.tsx"] == {"packages/ui/src/Button.tsx"}
    assert idx.package["apps/web/src/page.tsx"] == "apps/web"
    assert idx.package["packages/ui/src/Button.tsx"] == "packages/ui"
    rel = idx.related("apps/web/src/page.tsx")
    assert rel == [
        {"file": "packages/ui/src/Button.tsx", "why": "imports"},
        {"file": "apps/web/src/terms/page.tsx", "why": "legal"},
        {"file": "apps/web/src/app/layout.tsx", "why": "shell"},
    ]


def test_related_two_hops_skips_tests_and_respects_limit(tmp_path):
    files = write(
        tmp_path,
        {
            "src/a.ts": "import './b'",
            "src/b.ts": "import './c'",
            "src/c.ts": "export {}",
            "src/a.test.ts": "import './a'",
            "src/d.ts": "import './a'",
        },
    )
    idx = build_index(tmp_path, files)
    assert idx.related("src/a.ts") == [
        {"file": "src/b.ts", "why": "imports"},
        {"file": "src/d.ts", "why": "imported-by"},
        {"file": "src/c.ts", "why": "hop2"},
    ]
    assert len(idx.related("src/a.ts", limit=1)) == 1
    assert idx.related("src/a.test.ts")[0] == {"file": "src/a.ts", "why": "imports"}
    assert idx.related("nope.ts") == []


def test_candidate_units_group_by_policy_and_file(tmp_path):
    from policypack.index.units import candidate_units

    files = write(
        tmp_path,
        {
            "src/pages/Signup.tsx": "import { Agree } from '../Agree'\nexport default () => <form/>",
            "src/Agree.tsx": "export const Agree = () => <input/>",
        },
    )
    idx = build_index(tmp_path, files)
    findings = [
        {"policy": "kr.pipa.22-2", "rule": "a", "file": "src/pages/Signup.tsx", "line": 2, "outcome": "needs-review"},
        {"policy": "kr.pipa.22-2", "rule": "b", "file": "src/pages/Signup.tsx", "line": 1, "outcome": "uncertain"},
        {"policy": "kr.ai-basic-act.31", "rule": "c", "file": "src/gone.ts", "outcome": "needs-review"},
    ]
    units = [u.as_dict() for u in candidate_units(findings, idx)]
    assert units == [
        {
            "policy": "kr.ai-basic-act.31",
            "entry": "src/gone.ts",
            "rules": ["c"],
            "outcomes": ["needs-review"],
            "lines": [],
            "role": "unknown",
            "related": [],
        },
        {
            "policy": "kr.pipa.22-2",
            "entry": "src/pages/Signup.tsx",
            "rules": ["a", "b"],
            "outcomes": ["needs-review", "uncertain"],
            "lines": [1, 2],
            "role": "screen",
            "related": [{"file": "src/Agree.tsx", "why": "imports"}],
        },
    ]


def test_related_puts_constants_last_and_legal_before_hop2(tmp_path):
    files = write(
        tmp_path,
        {
            "src/Chat.tsx": (
                "import C from './constants/Color'\nimport { u } from './useChat'\nexport default () => <div/>"
            ),
            "src/constants/Color.ts": "export default {}",
            "src/useChat.ts": "import './api'",
            "src/api.ts": "export {}",
            "src/pages/privacy.tsx": "export default () => <p/>",
        },
    )
    idx = build_index(tmp_path, files)
    assert idx.related("src/Chat.tsx") == [
        {"file": "src/useChat.ts", "why": "imports"},
        {"file": "src/pages/privacy.tsx", "why": "legal"},
        {"file": "src/api.ts", "why": "hop2"},
        {"file": "src/constants/Color.ts", "why": "low"},
    ]

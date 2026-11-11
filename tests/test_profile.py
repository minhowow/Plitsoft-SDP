"""저장소 프로필(policypack profile): 기능 알아보기와 기능–의무 표. 모델 호출 0회."""

from __future__ import annotations

import json

from policypack.cli import main
from policypack.profile import load_duties, load_features, package_of, path_words, profile


def test_path_words_split_names_and_join_neighbours():
    words = path_words("src/pages/SignUpScreen.tsx")
    assert {"sign", "up", "signup", "screen", "pages"} <= words
    assert "order" not in path_words("src/styles/border.ts")
    assert {"ai", "chat"} <= path_words("src/AIChat/index.tsx")


def test_package_names_from_import_specifiers():
    assert package_of("@tosspayments/payment-sdk/dist") == "@tosspayments/payment-sdk"
    assert package_of("firebase/app") == "firebase"
    assert package_of("./local") is None
    assert package_of("@/components/x") is None


def test_every_duty_has_one_feature_and_candidates_follow_the_rule():
    features = {f["id"] for f in load_features()["features"]} | {"common", "status"}
    duties = load_duties()
    assert len(duties) == len({d["id"] for d in duties}) == 795
    assert {d["feature"] for d in duties} <= features
    for d in duties:
        if d["scope"] == "sector":
            assert d["feature"] == "status"
        assert d["review_candidate"] == (
            d["quote_check"] == "pass"
            and d["confidence"] == "high"
            and d["scope"] in ("general", "domain")
            and d["feature"] != "status"
        )


def test_profile_finds_features_and_keeps_test_only_signals_apart(tmp_path, capsys):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"openai": "^4.0.0"}}))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "answer.ts").write_text(
        'import OpenAI from "openai";\nconst c = new OpenAI();\n'
        "// c.chat.completions.create 는 주석이라 세지 않는다\n"
        'export const ask = (q: string) => c.chat.completions.create({ model: "m", messages: [] });\n'
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "checkout.test.ts").write_text("it('pays', () => {});\n")

    assert main(["profile", str(tmp_path)]) == 0
    doc = json.loads(capsys.readouterr().out)
    found = {f["id"]: f for f in doc["features"]}
    assert {"genai", "external-transfer"} <= found.keys()
    calls = [e for e in found["genai"]["evidence"] if e["signal"] == "call"]
    assert [(e["file"], e["line"]) for e in calls] == [("src/answer.ts", 4)]
    assert found["genai"]["duties"]["count"] > 0
    assert [t["id"] for t in doc["test_only"]] == ["payment"]
    assert doc["service_features"] >= 1 and "common" in doc and "note" not in doc


def test_a_repository_without_service_features_says_so(tmp_path):
    (tmp_path / "sum.js").write_text("export const sum = (a, b) => a + b;\n")
    doc = profile(tmp_path)
    assert doc["features"] == [] and doc["service_features"] == 0
    assert "note" in doc and "common" not in doc
    assert doc["totals"] == {"features": 0, "duties": 0, "review_candidates": 0}

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


def test_a_react_native_app_is_not_a_website(tmp_path):
    """화면 파일이 있어도 모바일 앱 틀만 있으면 웹이 아니다. React Native 앱에 웹 접근성 의무를 붙이지 않는다."""
    deps = {"react": "18", "react-native": "0.74", "expo": "51", "react-dom": "18"}
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": deps}))
    (tmp_path / "App.tsx").write_text("export default function App() {\n  return <View><Text>hi</Text></View>;\n}\n")
    doc = profile(tmp_path)
    assert doc["platforms"] == ["mobile"]
    assert [f["id"] for f in doc["features"]] == ["mobile-app"]

    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {**deps, "next": "14"}}))
    doc = profile(tmp_path)
    assert doc["platforms"] == ["web", "mobile"] and {"web-ui", "mobile-app"} <= {f["id"] for f in doc["features"]}


def test_call_signals_count_only_code_and_urls_only_at_the_start_of_a_string(tmp_path):
    """문장 속 'openai.responses.create'(웹 저장소의 사례 글)와 주석은 세지 않는다.
    주소는 문자열이 그 주소로 시작할 때만 센다."""
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"express": "4"}}))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "story.ts").write_text(
        'export const text = "호출 모양(`openai.responses.create`)을 규칙이 알아보지 못했다";\n'
        "// client.chat.completions.create 는 주석이다\n"
        'export const doc = "자세한 것은 api.openai.com 을 본다";\n'
    )
    assert "genai" not in {f["id"] for f in profile(tmp_path)["features"]}
    (tmp_path / "src" / "ask.ts").write_text(
        "export const ask = async (q: string) =>\n"
        '  fetch("https://api.openai.com/v1/responses", { method: "POST", body: JSON.stringify({ input: `${q}` }) });\n'
        "export const again = (c: any) => c.responses.create({ input: `${name.trim()}` });\n"
    )
    found = {f["id"]: f for f in profile(tmp_path)["features"]}
    ev = {(e["signal"], e["value"], e["file"], e["line"]) for e in found["genai"]["evidence"]}
    assert ("url", "api.openai.com", "src/ask.ts", 2) in ev and ("call", "responses.create", "src/ask.ts", 3) in ev
    assert not any(e[2] == "src/story.ts" for e in ev)

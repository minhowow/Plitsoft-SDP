# policypack — 국내 법·정책 관점 코드 검토

아주대학교 2026-2 자기주도프로젝트 · 플리트소프트 연계 과제. (개발 중)

JS/TS 코드에서 **국내 법·정책상 검토가 필요한 지점**을 찾는 로컬 CLI 도구다. 코드를 누가
썼는지는 보지 않는다. 사람이 쓴 코드든 AI 코딩 도구가 만든 코드든 같은 규칙으로 검사한다.

구조는 Semgrep 을 감싸는 래퍼다. 앞에서는 정책 팩을 Semgrep 규칙으로 바꿔 Semgrep 을 한 번 돌리고,
뒤에서는 그 결과를 정책마다 참·거짓·모름으로 판정한 뒤, 정적으로 풀리지 않은 곳에만 AI를 부른다.
생성형 AI 에 관한 의무(인공지능기본법 제31조)는 정책 팩 kr-core 에 든 정책 가운데 하나다. 도구의
대상이 AI 가 만든 코드라는 뜻이 아니다.

출력은 "위반"이 아니라 **검토 필요 + 근거 조문 + 확인 질문**이다. 법률 자문이 아니다.

## 어떻게 판정하나

정책 하나는 법 조항 하나다. 그 아래 규칙이 있고, 규칙의 조건은 두 종류다.
Semgrep 문법을 그대로 쓰는 정적 조건과, `ai:` 블록이다. 해석기는

1. 모든 정책의 정적 조건을 **Semgrep 규칙 하나로 합쳐 한 번만** 돌리고 (엔진은 고치지 않는다),
2. 조건마다 값을 **참·거짓·모름** 세 값으로 정하고 — 적용 조건(`applies-when`)은 모두 참이어야,
   적법한 대안(`compliant-if-any`)은 하나만 참이면 된다,
3. 정적 조건으로 결론이 나지 않는 곳에서만 **AI를 부른다**.

```yaml
compliant-if-any:            # 적법한 대안. 하나라도 참이면 준수
  - id: under14-branch       # 정적 — 참이면 AI를 부르지 않는다
    static:
      pattern: if ($X < 14) { ... }
  - id: ai-guard             # 정적으로 결론이 안 날 때만
    ai:
      question: 이 코드에 만 14세 미만 가입을 막거나 법정대리인 동의를 확인하는 처리가 있는가?
      evidence: required     # '예'는 코드의 실제 줄을 인용해야 인정된다
```

**방향성 신뢰**가 설계의 중심이다. 약한 근거 — 이름·정규식 매치, 인용 없는 AI 답, 주석 속 문구 —
는 경고를 **올릴 수는 있어도 내릴 수는 없다**.

- **약한 대안은 혼자 경고를 풀지 못한다.** 이름·문자열만 본 정적 대안(`strength: weak`)이 참이면
  판정자에게 다시 묻는다. 판정자가 없으면 그런 곳은 '불확실'로 남는다.
- **AI 의 '예'는 인용이 있어야 한다.** 인용 전체가 코드에 있어야 하고, 주석에서만 찾은 인용은 받지 않는다.
  줄 끝에 주석이 달린 코드 줄은 코드 부분이 실재하면 받는다. "이 문구가 코드에 있는가"를 묻는 조건은
  `evidence: strict` 로 적어 줄 끝 주석까지 받지 않는다. 인용이 틀리면 '거짓'이 아니라 '모름'이 되어
  경고가 남는다.
- **AI 차례를 숨기지 않는다.** 판정자가 없거나(`--judge none`, 기본) 답하지 못하면, AI 에게 물었어야 할
  곳을 'AI 확인 필요'로 보고한다. 그 AI 대안은 판정에 넣지 않으므로 정적 판정이 그대로 남는다. 판정자가
  없을 때와 고장 났을 때 판정이 같다. 판정자가 연달아 세 번 시간 안에 답하지 않으면 그 실행에서는 더 묻지
  않는다.
- **AI 가 푼 것을 남긴다.** AI 의 '예'로 풀린 경고(인용한 줄과 관문 결과)와 적용 질문의 '아니오'로 빠진
  판정을 글·JSON·SARIF 에 싣는다. 관문은 인용이 코드에 있는지만 보고 규칙과 관련 있는지는 보지 않으므로,
  사람이 검토할 수 있어야 한다.

## 설치

아직 PyPI 에 올리지 않았다(계획상 14주차). 지금은 저장소에서 설치한다. semgrep 은 따로 설치하지 않는다.
policypack 이 의존성으로 선언해 두어서 함께 깔린다.

```bash
uv tool install .              # PATH 에는 policypack 명령 하나만 생긴다
```

공개 뒤에는 이렇게 쓴다.

```bash
uvx policypack scan --staged   # 설치 없이 한 번. uv 만 있으면 되고, Python 이 없으면 uv 가 받는다
uv tool install policypack     # 또는 pipx install policypack
```

전역 `pip install` 은 권하지 않는다. semgrep 이 의존성 몇 개를 좁게 고정해서(`click~=8.4.2`,
`opentelemetry~=1.37` 등) 같은 환경의 다른 패키지와 부딪힐 수 있다. 격리 설치(uv tool·pipx·uvx·
pre-commit)면 문제없다.

- **필요한 것**: Python 3.10 이상. macOS 기본 `python3` 은 3.9 라 안 된다. uv 를 쓰면 uv 가 알아서 받는다.
- **크기**: 처음 설치할 때 63~86MB 를 내려받고 디스크 약 260MB 를 쓴다. 대부분이 semgrep 엔진이다
  (`semgrep-core` 하나가 약 210MB).
- **플랫폼**: macOS(x86_64 10.14+, arm64 11+), Linux(x86_64·aarch64, glibc 2.34 이상 또는 musl 1.2 —
  Ubuntu 20.04·Debian 11·RHEL 8·Amazon Linux 2 는 안 된다), Windows x64. 윈도는 Semgrep 쪽에서도
  beta 이고, 우리는 아직 윈도에서 돌려 보지 않았다.

커밋 전 훅(pre-commit 프레임워크)은 `.pre-commit-config.yaml` 에 이렇게 둔다. pre-commit 이 훅용
파이썬 환경을 만들고 semgrep 까지 설치한다.

```yaml
repos:
  - repo: <이 저장소 URL>
    rev: <태그>
    hooks:
      - id: policypack
```

훅에서 AI 판정자를 켜려면(`args: [--judge, claude-cli:haiku]`) `verbose: true` 도 함께 둔다. pre-commit 은
통과한 훅의 출력을 숨겨서, 무엇이 밖으로 나가는지 알리는 한 줄이 보이지 않는다.

GitHub Actions 의 호스티드 러너에는 Python 과 pipx 가 이미 있다. PyPI 에 올리기 전에는 저장소에서
설치한다. 이름만으로 설치하면(`pipx install policypack`) 아직 등록되지 않은 PyPI 이름을 찾게 되고,
누가 그 이름을 먼저 등록하면 남의 패키지가 저장소 권한을 가진 러너에서 돈다.

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- run: pipx install "git+<이 저장소 URL>@<태그>"
- run: policypack scan --diff origin/main --output-format sarif > policypack.sarif
```

## 써 보기

```bash
uv sync
uv run policypack scan src/                       # 정적 조건만 (AI 호출 0회)
uv run policypack scan src/ --explain             # 판정 경로까지
uv run policypack scan src/ --output-format sarif # 근거 조문이 help.markdown 에 실린다
uv run policypack scan --staged                    # 스테이징된 파일만 (커밋 전 훅)
uv run policypack scan --diff origin/main          # 분기점 이후 이 브랜치가 바꾼 파일만 (CI)
uv run policypack scan src/ --judge claude-cli:haiku  # 정적으로 결론이 안 난 곳만 AI 에게 묻는다
uv run policypack validate                        # 팩 문법·Semgrep 조건·조문 원문 해시·재검토 기한
uv run policypack test --strict                   # 팩의 픽스처 (모델 호출 0회)
uv run policypack doctor                          # 정적 백엔드 진단
```

1MB 초과·축소 번들·읽을 수 없는 파일·엔진이 읽지 못하는 확장자·UTF-8 이 아닌 파일은 검사하지 않은 파일로
보고서에 적는다. 생성물 디렉터리(node_modules·dist 등) 아래 파일은 전체 검사에서 적지 않고 뺀다(`--staged`·`--diff`
는 개수를 알린다). UTF-8 이 아닌 파일(EUC-KR 등)은 Semgrep 의 정규식 조건이 오류 없이 아무것도 찾지 못해서 뺀다.
보지 못한 사용자 코드라 '불확실'처럼 종료 코드에 센다. UTF-8 로 바꾸면 검사한다.

종료 코드는 `0` 검토할 것 없음 · `1` 검토 필요 · `2` 도구 오류다. CI에서
전자는 사람이 볼 일이고 후자는 파이프라인이 멈출 일이다. `--fail-on review` 면 확실한 '검토 필요'만,
기본 `uncertain` 이면 '불확실'까지 `1` 로 센다.

`--diff` 는 REF 와의 분기점(merge-base)을 찾아야 하므로 CI 에서는 전체 이력을 받는다
(GitHub Actions 라면 `actions/checkout` 에 `fetch-depth: 0`). 바뀐 JS/TS 파일이 없어도
`--output-format sarif` 는 빈 SARIF 를 내서 업로드 단계가 깨지지 않는다.

출력은 판정마다 셋을 함께 낸다. 어느 적법한 대안이 왜 안 맞았는지, 개발자에게
할 구체적인 질문, 그리고 근거 조문이다.

```
src/auth/signup.ts:12  검토 필요  만 14세 미만 아동의 개인정보 처리
    근거  개인정보 보호법 제22조의2 제1항
    · 만 14세 미만을 가르는 연령 분기가 보이지 않습니다.
      → 이 가입 흐름에서 만 14세 미만 사용자를 어떻게 가려내나요?
      고치려면: 생년월일로 만 나이를 계산해 14세 미만 분기를 두세요.
```

## 정책 팩

내장 팩은 `policies/kr-core` 다. 정책 다섯(아동 동의, 야간 광고, 광고 표기, 생성형 AI 결과물 표시,
생성형 AI 사전 고지)을 싣고, 패키지에 함께 실려 어느 저장소에서든 돈다. 다른 팩은 `--config` 로 준다.
문법은 `schemas/policy-pack-0.3.json`(편집기 자동 완성용)과 `src/policypack/model.py` 가 정한다.

- **조문 추적성.** 정책마다 근거 조문을 적고, 조문 원문을 팩 안의 `_legal/` 에 커밋한 뒤 그 해시를
  `text-sha256` 에 적는다. 원문 파일이 바뀌면 `validate` 가 기록된 해시와 실제 해시를 함께 보여 준다.
  조문을 다시 읽고 규칙을 손본 뒤 해시를 고친다.
- **재검토 기한.** `review.review-by` 가 지나면 `validate` 가 경고한다.
- **함수 단위 판정.** 규칙에 `scope: anchor` 와 `anchor-on`(적용 조건 id)을 적으면 파일이 아니라
  그 조건이 맞은 자리를 감싸는 가장 바깥 함수마다 판정한다. 대안은 그 함수와 겹치는 매치만, AI 의 '예'는
  그 함수 안의 줄 인용만 인정한다. 지금은 JavaScript·TypeScript 에서만 함수 경계를 얻는다.

정책을 쓰면 팩의 `tests/` 에 픽스처를 둔다. 코드는 손대지 않은 실제 파일이고, 기대 판정과
"판정자가 이렇게 답했다고 치자"는 옆의 `*.test.yaml` 에 적는다. 스텁 답도 근거 관문을
그대로 거친다 — 코드에 없는 줄을 인용한 '예'는 경고를 내리지 못한다. `--strict` 는
대안마다 그 대안 하나로 풀리는 픽스처가 없으면 실패로 센다. 혼자 풀 수 있는 정적 대안에는
그 대안을 흉내 내지만 풀리면 안 되는 음성 픽스처(`decoy-for`)도 요구한다. 조건 모양만 맞는
엉뚱한 코드(야간에만 보내는 시간 검사, 비밀번호 길이 `< 14`)가 경고를 푸는 것을 이것으로 잡는다.
약한 대안은 AI 확인 없이 풀지 못하므로 그 대안의 픽스처에는 AI 답 스텁이 있어야 한다.

## 라이선스와 배포

policypack 은 **MIT** 다(LICENSE). 자세한 목록은 [NOTICE](NOTICE) 에 있다. 요점 넷.

- **엔진은 Semgrep CE 이고 LGPL-2.1 이다.** 우리는 링크하지 않고 별도 프로그램으로 부른다
  — 규칙을 임시 파일에 쓰고 `semgrep scan --config … --json` 을 실행해 표준 출력을 읽는다.
  우리 배포물에는 Semgrep 코드·바이너리가 한 바이트도 없다. `pip install policypack` 이
  `semgrep==1.176.*` 를 PyPI 에서 함께 받아 설치한다(엔진 바이너리가 그 휠 안에 있다.
  플랫폼과 크기는 위 "설치" 절).
- **규칙은 전부 저자가 썼다.** Semgrep Registry 규칙은 한 건도 싣지 않고 실행 중에 받아
  오지도 않는다(`p/`·`r/`·`auto` 를 쓰지 않으며, 테스트가 이를 검사한다). 레지스트리 규칙은
  재배포와 서비스 제공이 금지돼 있어, 들이는 순간 이 도구를 공개 배포할 수 없게 된다.
- **정적 검사는 아무것도 외부로 보내지 않는다.** 아래 "외부 통신" 에 무엇을 막는지와 직접
  확인하는 방법을 적었다. 계정도 로그인도 필요 없다. 다만 `--judge claude-cli:…` 나
  `--judge anthropic:…` 를 쓰면 **판정 대상 코드가 그 API 로 나간다**(범위는 "외부 통신" 절).
  기본값은 모델을 부르지 않는 `--judge none` 이다.
- **바이너리를 동봉한 배포물은 만들지 않는다.** 이미지·단일 실행 파일·오프라인 설치본·사내
  미러는 모두 배포에 해당해 LGPL 제4조 의무가 생긴다. 컨테이너가 필요하면 이미지가 아니라
  Dockerfile 을 배포한다.

### 외부 통신

코드가 기계 밖으로 나가는 길은 AI 판정자 하나다. 판정자를 켜면, 규칙이 적용되는데 강한 정적 대안으로
준수가 확인되지 않은 파일(이름·정규식 같은 약한 근거로만 준수가 보이는 파일 포함)과, 적용 여부가
정적으로 정해지지 않아 적용 질문을 묻는 파일의 코드가 판정자에게 간다.

- 파일 단위 규칙(기본, kr-core 전부): 파일의 **전체 내용**(1MB 미만).
- 함수 단위 규칙(`scope: anchor`): 앵커를 감싼 **그 함수**와, 같은 파일에서 그 함수가 쓰는 최상위 선언(각 12줄
  까지)·import, 그 함수를 부르는 줄(이름 없는 콜백이면 같은 문장의 앞줄 8줄까지), 그 함수가 읽는 this 필드에
  값을 넣는 줄(합쳐 60줄·6000자까지). 다만
  - 앵커가 함수 밖에만 있거나 함수 경계를 얻지 못한 파일, 그리고 적용 여부를 AI에 묻는 질문(applies-ai)은
    파일 전체가 간다.
  - 함수 안팎에 앵커가 섞인 파일의 함수 밖 판정은 함수 본문을 비운 모듈 최상위 줄이 간다.

실행할 때 stderr 에 이 사실을 알린다.

판정자 CLI·SDK 는 사용자가 해 둔 설정을 따른다. `ANTHROPIC_BASE_URL`·Bedrock·Vertex 설정이 있으면
목적지가 바뀌고, Claude Code 텔레메트리 설정(`OTEL_LOG_USER_PROMPTS` 등)이 있으면 그 수집기에도
기록이 갈 수 있다. 사내 게이트웨이가 필수인 경우가 있어 끊지 않고, 고지에 실제 목적지를 함께 적는다.

semgrep 쪽에서는 이렇게 막는다.

- 텔레메트리와 판본 확인을 플래그(`--metrics=off`, `--disable-version-check`)와 환경변수로 끈다.
- **사용자가 semgrep 에 해 둔 설정은 물려주지 않는다.** `SEMGREP_` 로 시작하는 변수(로그인 토큰,
  `SEMGREP_BASELINE_REF` 등)를 모두 빼고, settings·로그·판본 캐시는 실행마다 만드는 임시 디렉터리를
  쓴다. 그래서 `semgrep login` 을 해 두었거나 CI 에 Semgrep 변수가 있어도 우리 결과는 같고,
  사용자 HOME 의 `~/.semgrep/` 도 건드리지 않는다.
- `--oss-only` 로 오픈 소스 엔진만 쓴다. `login`·`ci`·`--pro`·레지스트리(`p/`·`r/`·`auto`)는 부르지 않는다.

직접 확인할 수 있다. 127.0.0.1 에만 붙는 기록용 프록시와 가짜 토큰을 두고 돌려, 연결 시도가 0건인지 본다.

```bash
uv run pytest tests/test_isolation.py -v
```

Opengrep(Semgrep CE 의 LGPL-2.1 포크)으로 갈아탈 수도 있다. 라이선스 등급은 같고, 백엔드
이음매(`StaticBackend` 프로토콜)는 `name`·`version()`·`run()` 셋뿐이다. 지금 갈아타지 않는
이유는 PyPI 에 없어서 "한 줄 설치"가 깨지기 때문이다.

## 판정자

프론티어 모델만 쓴다. 어댑터는 두 개다.

- `claude-cli:<모델>` — `claude` CLI를 단발 판정자로 부른다. API 키가 필요 없다.
- `anthropic:<모델>` — `ANTHROPIC_API_KEY` 를 쓴다(`uv sync --extra api` 로 SDK 를 설치).

두 경우 모두 **판정 대상 코드가 외부 API로 나간다**(범위는 "외부 통신" 절). 개인정보 점검 도구의 성질상
이 점은 쓰기 전에 알아야 한다. 한 번 실행하는 동안 같은 질문을 같은 코드로 두 번 묻지 않는다.

## 저장소 구성

| 경로 | 내용 |
|---|---|
| `src/policypack/` | 제품 코드 |
| `policies/kr-core/` | 내장 정책 팩, 조문 원문(`_legal/`), 픽스처(`tests/`) |
| `schemas/` | 정책 팩·테스트 파일의 JSON Schema (`policypack schema --write` 가 만든다) |
| `tests/` | pytest |

측정·연구 기록과 보고서는 태그 `archive/research-2026-09-29` 에 남아 있다.

## 자주 묻는 것

**semgrep 을 먼저 설치해야 하나요?** 아니요. policypack 을 설치하면 함께 깔립니다. 이미 다른
semgrep 이 있어도 policypack 은 함께 설치된 판을 씁니다.

**Semgrep 계정이나 로그인이 필요한가요? 로그인해 두면 코드가 나가나요?** 필요 없습니다.
로그인해 두었어도 policypack 은 그 설정을 읽지 않습니다. 연결 시도가 0건인 것을 시험으로 확인합니다.

**왜 Semgrep 공식 규칙을 쓰지 않나요?** Semgrep Rules License 가 규칙의 배포와 서비스 제공을
금지하기 때문입니다. 엔진이 아니라 규칙에 붙은 조건이라 어느 엔진을 써도 같습니다. 이 도구의
규칙(국내 법 조항 정책 팩)은 전부 직접 썼습니다.

## 면책

이 도구는 법률 자문이 아니다. 검토가 필요한 지점을 식별할 뿐이고, 조문 해석과 최종 판단은
사람이 한다. 정책 팩의 법 문구는 검토 중이다.

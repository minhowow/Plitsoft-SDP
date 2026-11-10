# 출력 계약 — scan 의 JSON 보고서

웹 서비스(`Plitsoft-SDP-Web`)와 CI 가 읽는 `policypack scan --output-format json` 의 약속이다. SARIF·GitLab Code
Quality(`--output-format gitlab`)는 그 형식의 규격을 따르고, 지문은 셋이 같은 값이다.
스키마는 [`schemas/report-1.json`](../schemas/report-1.json)(JSON Schema 2020-12)이고, `tests/test_report_schema.py` 가
실제 보고서(판정자 없음, 판정자가 푼 것·뺀 것, 에이전트 세 방식, 서비스에 닿지 못한 에이전트)로 검사한다.

## 웹이 고정할 판

- 11주 인계: 태그 `handoff-w11`(원격 `origin` 의 가지 `interim-report-f1-evaluation`). 이 문서와 스키마가 그 판의 계약이다.
- 13주에 도구 판 태그(`v0.4.0`)를 따로 단다. 그 전까지 웹은 `handoff-w11` 을 고정한다.

## 판 올리기

- `schema_version` 은 지금 1 이다. 있던 키가 없어지거나 뜻이 바뀌면 올린다. 키를 더할 때는 올리지 않는다.
- 그래서 받는 쪽은 **모르는 키를 무시**한다. 스키마는 이 CLI 판이 내는 키를 모두 적고 그 밖의 키를 막는데, 그것은
  CLI 의 시험이 스키마를 함께 고치게 하려는 것이다. 웹이 이 스키마로 엄격하게 검사하면 CLI 가 키를 더할 때 깨진다.
- 파일 경로는 모두 검사 루트(git 저장소면 그 뿌리)에서의 상대 경로다.

## 에이전트 검토(`--agent`)의 키

`run.agent`, `findings[].agent` 와 그 안의 `reason`·`citations` 는 `schema_version` 1 의 계약이다. 정확도 실험을 하지
않기로 하면서(결정 0004) 평가용 키라는 구분은 없어졌다.

| 키 | 뜻 |
|---|---|
| `run.agent.judge`, `mode` | 에이전트 판정기(`agent:anthropic:<실제 모델 id>`)와 방식(review·combined·independent) |
| `run.agent.records[]` | 진입 파일 하나에 대한 답(`verdict`)과 반영 결과(`action`), 인용(`citations`) |
| `run.agent.discover`, `recheck` | 결합 방식의 찾기·재확인 단계. 모양은 `run.agent` 와 같다 |
| `run.agent.questions[].sent` | 그 질문에서 밖으로 나간 것: 읽은 파일, 검색어, 검색 결과로 줄이 나간 파일(`matched`), 목록으로 나간 이름 수(`listed`), 가린 비밀값 수. `refused` 는 읽기를 거절한 비밀 파일(나가지 않았다) |
| `unanswered`, `run.agent.questions_skipped`, `skipped_reasons` | 답을 받지 못한 질문, 보내지 않은 질문과 그 까닭(`unreachable` 서비스에 닿지 못함, `time` 시간 상한) |
| `run.agent.seconds` | 에이전트 단계(review·찾기·재확인)에 걸린 시간 |
| `findings[].agent` | 그 경고에 대한 에이전트의 답. 에이전트를 켜지 않으면 키가 없다 |
| `raw` | 모델이 낸 글 그대로(읽지 못했거나 잘린 답일 때만). 진단용이고 코드가 섞일 수 있어 화면에 그대로 싣지 않는다 |

### 인용과 줄 번호

- 인용의 `ok` 는 관문 결과다. `why` 가 `grounded` 인 인용만 경고를 풀거나 새 경고의 근거가 된다.
- `ok` 인 인용의 `line` 은 관문이 코드에서 다시 구한 줄(인용이 시작하는 줄)이다. 모델이 적은 줄이 다르면 그 값이
  `line_model` 에 있다. `ok` 가 아닌 인용의 `line` 은 모델이 적은 값 그대로다.
- 에이전트가 낸 경고(`rule` 이 `agent-independent`·`agent-discovered`)의 `line` 도 진입 파일에서 통과한 인용의 줄로
  맞춘다. 모델이 다른 줄을 적었으면 `findings[].agent.line_model` 에 있다.
- 관문은 인용이 코드에 글자 그대로 있는지만 본다. 문자열 리터럴 속 인용과 문서 파일(.md 등) 줄의 인용은 거르지
  않는다. 화면의 고지 문구는 대개 문자열이고, 처리방침이 문서 파일인 서비스도 있어서 거르면 맞는 근거를 버린다.

### `--agent` 에서 달라지는 것 (`schema_version` 은 그대로)

- `run.units` 의 관계(`findings + ai_cleared + static_cleared`)는 에이전트를 끈 보고서에서만 맞다. 에이전트가 푼
  경고는 `findings` 에서 빠지고 `run.agent.records[]`(재확인 단계면 `recheck.records[]`)에 `action: cleared` 로 남는다.
  에이전트가 새로 찾은 경고는 팩 밖의 규칙 id(`agent-independent`, `agent-discovered`)로 `findings` 에 들어간다.
- `--agent` 만 켜고 `--judge` 를 끄면 `run.judge` 는 null 이다. AI 를 썼는지는 `run.judge` 또는 `run.agent` 로 본다.
- 찾기 단계에서 찾은 곳의 인용은 `discover.records[]` 에 있고, 재확인 단계가 다시 낸 인용은 `recheck.records[]` 에 있다.
- 독립 검토(`independent`)에는 정적 판정이 없다. 답을 받지 못한 정책이 있으면 경고가 없어도 종료 코드가 1 이다
  (`--fail-on uncertain`, 기본).

## 아직 없는 것

- 정책별 요약(정책마다 단위 수와 상태별 수), 결과에 실린 CLI 커밋·검사 시각, 팩 메타데이터 내보내기 명령.
- 찾기 단계는 정책마다 질문 하나라 `--agent-max-units` 로 묶지 않는다(`--agent-time-limit` 으로 묶는다).

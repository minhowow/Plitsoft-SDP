# 출력 계약 — scan 의 JSON 보고서

웹 서비스(`Plitsoft-SDP-Web`)와 CI 가 읽는 `policypack scan --output-format json` 의 약속이다. SARIF·GitLab Code
Quality(`--output-format gitlab`)는 그 형식의 규격을 따르고, 지문은 셋이 같은 값이다.
스키마는 [`schemas/report-1.json`](../schemas/report-1.json)(JSON Schema 2020-12)이고, `tests/test_report_schema.py` 가
실제 보고서(판정자 없음, 판정자가 푼 것·뺀 것, 에이전트 세 방식, 서비스에 닿지 못한 에이전트)로 검사한다.

## 웹이 고정할 판

- 11주 인계: 태그 `handoff-w11`(원격 `origin` 의 가지 `interim-report-f1-evaluation`). 이 문서와 스키마가 그 판의 계약이다.
- 11주 두 번째 인계(11/11): 태그 `handoff-w11-2`(가지 `main`). 발견마다 파일 역할을 싣고(아래), 배열·라우터의 `push`
  를 광고 발송으로 세지 않는다. `handoff-w11` 에 키를 더하기만 했다.
- 13주에 도구 판 태그(`v0.4.0`)를 따로 단다. 그 전까지 웹은 `handoff-w11-2` 를 고정한다.

## 판 올리기

- `schema_version` 은 지금 1 이다. 있던 키가 없어지거나 뜻이 바뀌면 올린다. 키를 더할 때는 올리지 않는다.
- 그래서 받는 쪽은 **모르는 키를 무시**한다. 스키마는 이 CLI 판이 내는 키를 모두 적고 그 밖의 키를 막는데, 그것은
  CLI 의 시험이 스키마를 함께 고치게 하려는 것이다. 웹이 이 스키마로 엄격하게 검사하면 CLI 가 키를 더할 때 깨진다.
- 파일 경로는 모두 검사 루트(git 저장소면 그 뿌리)에서의 상대 경로다.

## 파일 역할의 키 (`handoff-w11-2` 부터)

| 키 | 뜻 |
|---|---|
| `findings[].role` | 그 파일의 역할. `test`(시험·픽스처·목업·스토리, 경로로만 고른다), `config`(설정), `server`, `screen`, `other` |
| `run.finding_counts` | `total`, `service`(server·screen·other 의 발견), `non_service`(test·config 의 발견), `by_role`(역할마다 수) |

- 역할은 `index/roles.py` 가 경로와 내용의 모양으로 고른 힌트다. 판정, `findings` 의 목록, 종료 코드는 역할을 보지 않는다.
  시험 파일의 발견도 그대로 `findings` 에 있다. 웹은 `role` 로 나눠 보이면 된다.
- 글 출력(`full`·`concise`)은 test·config 파일의 발견을 뒤에 따로 묶고 요약에 그 수를 적는다.
- 이 키가 없는 보고서(`handoff-w11` 판, 11/11 의 사례 실행 결과)는 역할을 모르는 것으로 읽는다.

## 판정자(`--judge`)의 키

`run.judge`(실제 모델 id), `run.judge_usage`(토큰 합), `run.judge_masked`(보내기 전에 가린 비밀값 수, 종류별. 가린 것이
있을 때만), `questions_sent`·`questions_skipped`.
시험·픽스처·설정 파일(`findings[].role` 이 test·config)은 판정자에게 묻지 않는다. 그 경고는 판정자가 없을 때와 같이 남고
`untested_reasons` 에 `test-file` 이 붙는다(11/11: 정책 팩 픽스처 310개가 있는 저장소에서 질문 367개 → 0개).

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

## 저장소 프로필(`policypack profile <폴더>`, 11/11 부터)

모델을 부르지 않는다. 저장소가 하는 일(기능)과 그 기능에 걸릴 수 있는 의무를 낸다. 판단은 하지 않는다(목록 층).
`profile_version` 은 1 이고 위 보고서와 같은 판 규칙(키를 더할 때는 그대로)을 따른다.

| 키 | 뜻 |
|---|---|
| `features[]` | 감지된 기능(`id`, `name`). `evidence[]` 는 근거 파일·줄·신호 종류(`package`·`import`·`call`·`url`·`path`·`screens`. `call` 은 문자열·주석 밖의 코드에서만, `url` 은 문자열이 그 주소로 시작할 때만 센다)·본 것, 앞의 5개만 싣고 전체 수는 `evidence_total` |
| `features[].duties` | 그 기능에 붙은 의무 `count`, 검토 층 후보 수 `review_candidates`, `items[]`(id, 법, 조문, 제목, 의무 한 줄, 법제처 링크, 후보 여부, 조문 인용 대조 결과) |
| `service_features` | 화면·앱(`web-ui`·`mobile-app`)을 뺀 기능 수. 0 이면 `note` 가 그 사실을 적고 `common` 이 없다 |
| `common` | 거의 모든 서비스에 걸리는 의무(처리방침·안전조치 등). 서비스 기능이 하나라도 있을 때만 |
| `status` | 운영 주체의 지위(공공기관·금융회사 등)로 걸리는 의무 수. 코드로 가리지 않아 목록은 싣지 않는다 |
| `test_only[]` | 시험·픽스처·설정 파일에서만 본 기능 신호. 기능으로 세지 않는다 |
| `files`, `totals` | 본 파일 수(서비스 코드 / 시험·설정, package.json), 기능·의무·후보 합계 |
| `platforms` | web·mobile·server. 모바일 앱 틀(react-native·expo 등)만 있으면 화면 파일이 있어도 웹이 아니어서 `web-ui` 기능이 없다 |
| `goods[]` | 특정 품목(주류·도서·안경·전기용품·농수산물·청소년유해약물)의 신호(경로 낱말, 소스 글의 낱말 `word`)와 그 품목에만 걸리는 의무 id(`duties`). 11/12 부터 |

기능과 신호는 `src/policypack/profile/features.yaml`, 기능–의무 표는 `src/policypack/profile/duties.jsonl`(만드는 법은
`scripts/lawmap_table.py`)에 있다.

## 저장소 검토(`policypack review <폴더>`, 11/11 부터)

스키마는 [`schemas/review-2.json`](../schemas/review-2.json), `review_version` 은 2 다(1 에서 '확인할 것'을 세 갈래로 나누고
부재 증명을 더해 판을 올렸다. 키를 더할 때는 그대로).
조사 모델(`--model`, 기본 haiku)이 저장소를 읽고, 다른 모델(`--checker`, 기본 sonnet)이 반박한다. 질문은 기본으로
의무 하나씩이다(`--batch duty`; `feature` 는 기능 하나에 의무 8개까지 묶어 싸다). 모델이 읽은 파일의 코드가 밖으로
나간다(비밀값은 가리고 .env 등은 읽지 않는다). `--plan` 은 모델 없이 물을 의무와 질문 수만 낸다. `--reuse <앞 결과>` 는
같은 저장소·커밋의 앞 결과에서 이해 단계(요약·기능·개인정보 흐름)를 되살려 묻지 않는다(인용은 관문에 다시 건다).

| 키 | 뜻 |
|---|---|
| `summary` | 체크리스트의 갈래별 수(`counts`), 갈래 이름(`labels`), 맨 위 다섯 건의 의무 id(`top`), 한 줄로 묶어 보일 항목(`groups`: 품목 신호가 없어 묻지 않은 품목 의무, `id` goods) |
| `profile` | 커밋(`commit`), 플랫폼(`platforms`: web·mobile·server), 서비스 요약, 기능(`sources`: signal·model·static, 모델이 더한 근거 `model_citations`, 인용과 함께 뺀 것은 `removed`), 품목 신호(`goods`) |
| `data_flow` | 개인정보 흐름. `nodes[]`(input·server·store·external, 다루는 항목 `data`, 인용) 와 `edges[]`(from→to). 인용이 관문을 통과한 것만 |
| `obligations.listed[]` | 목록 층: 감지된 기능과 거의 모든 서비스에 걸릴 수 있는 의무. `in_checklist` 는 검토 층에 들었는지 |
| `checklist[]` | 검토 층. 이미 갈래 순으로 늘어서 있고 `rank` 가 1 부터다. 의무마다 `status`·`status_label`, 인용 `citations`, 부재를 보인 검색 `searches`, 개발자에게 물을 `question`, 조사 모델의 첫 답 `first`, 반박 `verification`(upheld · overturned · overturn-ungrounded · not-run, 조문 밖 요건이었는지 `off_quote`), 내장 팩 정적 결과 `static`, 조건은 있는데 없는 지킨 처리 `missing`(예: "약관 고지 화면이 없음"), 묻지 않은 품목 의무의 묶음 `group`(goods) |
| `first`·`verification` 의 덧붙임(11/12) | 답이 적은 걸리는 조건 `applies`(예·아니오·모름)·`condition`, 없는 것 `missing`, 충족 인용의 성격 `shows`(행위·이름·기본값), 관문이 답을 바꾼 까닭 `gate`(`why`: condition-present · no-condition · name-or-default · audience · missing-check · applies-unknown · free-input · other-side, `note` 는 `reason` 앞에도 붙는다). '해당 없음'의 근거 `basis`(처리 없음·확인 장치 없음, 같은 날 덧붙임). 걸리는 조건을 본 곳 `trigger`(입력란·처리·저장 · 자유 입력 추측, 11/13 덧붙임). 인용의 `why` 가 `profile` 이면 모델의 인용이 아니라 기능이 있다는 프로필 신호(걸리는 조건의 근거)다. `config-value` 면 설정 파일의 줄이지만 주소·호스트 값이 있어 받은 인용이다 |
| `run` | 모델, 묶음, 저장소에 없는 쪽(`lacks`: screen 이면 서버만, server 면 화면만), 상한, 시간, 호출 수, 사용량, 어림 금액(공식 단가를 호출마다 매겨 더한 값), 상태·반박 결과별 수, 인용과 관문이 거절한 수, 검색과 다시 돌려 맞지 않은 수, 못 물은 의무(`not_asked`), 가린 비밀값, 읽지 않은 비밀 파일, 질문마다의 기록 |

상태(갈래 순):

| status | 이름 | 받는 조건 |
|---|---|---|
| `seen-in-code` | 확인할 것 — 코드에서 본 것 | 걸리는 조건의 인용이 관문을 통과했다. 지킨 근거는 찾지 못했다(`missing`). 조건은 있는데 지킨 처리가 없다는 '해당 없음', 그 기능이 있으면 걸리는 의무(`features.yaml` 의 `whenever`)에 기능이 있는데 낸 '해당 없음', 이름·기본값뿐인 '충족', 그 기능이 기능 신호·인용으로 확인됐는데 그 기능이 있으면 걸리는 의무에 낸 '해당 여부'도 여기로 온다 |
| `check-outside` | 확인할 것 — 저장소 밖에서 | 배포 설정·처리방침·저장소에 없는 서버를 봐야 한다. 인용이 관문을 통과하지 못한 '코드에서 본 것'·'충족'도 여기로 온다. 저장소가 서버만 또는 화면만이면(`run.lacks`) 반대쪽이 하는 의무(`features.yaml` 의 `sides`)의 '코드에서 본 것'도 여기다(`gate` other-side) |
| `check-applicability` | 확인할 것 — 해당 여부부터 | 걸리는지가 사업자의 판단이다(고영향 AI, 사내 도구, 업종). 반박하지 않는다. 걸리는 조건이 없다는 말 없이 낸 '해당 없음', 걸리는지 모른다고 한(`applies` 모름) '확인할 것'(그 기능이 있으면 걸리는 의무는 빼고), 나이·본인·지역을 확인하는 장치가 없다는 것을 근거로 든 '해당 없음'(`basis` 확인 장치 없음)과 이용자가 누구인지에 걸리는 의무(`features.yaml` 의 `audience`: 아동·미성년자·청소년)의 '해당 없음', 품목 신호가 없어 묻지 않은 품목 의무(`not_answered` goods-not-detected, 갈래의 맨 뒤), AI 기능은 있는데 생성형 AI 신호(꾸러미·import·호출·주소, 정적 검사, 그 글자가 있는 인용)가 없어 묻지 않은 AI 사전 고지·결과물 표시(`not_answered` not-generative)도 여기다 |
| `unknown` | 모름(묻지 못함) | 상한·실패로 답이 없다. `not_answered` 에 까닭 |
| `evidence-found` | 충족 근거 있음 | 조문이 요구하는 행위 자체를 보이는 줄(`shows` 행위)의 인용이 관문을 통과했다 |
| `likely-not-applicable` | 걸리지 않는 것으로 보임(확인 안 됨) | 걸리는 조건 자체가 없다고 했지만(`applies` 아니오·`condition`·`basis` 처리 없음) 검색 증명이 없거나 맞지 않았다. 걸리는 조건이 이용자가 자유 입력·사진에 넣을 수 있다는 추측뿐인 '확인할 것'(`trigger` 자유 입력 추측)도 여기다. 그 추측으로 반박이 뒤집으려 하면 받지 않는다. 확인 목록에 올리지 않는다 |
| `not-applicable` | 해당 없음(검색으로 확인) | 걸리는 조건 자체가 없다고 했고(`applies` 아니오·`condition`·`basis` 처리 없음), 그 조건을 찾은 검색(정규식·줄 수)을 도구가 저장소에서 다시 돌려 줄 수가 같았다 |

- 인용은 시험·설정 파일의 줄이면 받지 않는다. 질문에 넣는 요건은 조문 인용에 있는 것만이다.
- 반박이 뒤집을 때도 같은 조건(있다는 말은 인용, 없다는 말은 걸리는 조건이 없다는 답과 검색, 충족은 행위 자체의 인용)을
  넘어야 받는다.
- 묻는 순서와 체크리스트의 같은 갈래 안 순서: 기능은 거의 모든 서비스·가입·AI·외부 전송이 먼저, 기능 안에서는 일반 범위 →
  그 기능이 있으면 걸리는 의무 → 흔한 것(의무 표의 `freq`) → 확신 높은 것이고 품목 의무가 맨 뒤다. 금액 상한에 걸려도
  핵심 의무는 묻는다.
- 검색 도구는 결과를 60줄에서 잘라 보여 줄 때 맞는 줄의 전체 수를 함께 알려 주고, 관문은 그 전체 수와 맞춰 본다.

## 아직 없는 것

- 정책별 요약(정책마다 단위 수와 상태별 수), 결과에 실린 CLI 커밋·검사 시각, 팩 메타데이터 내보내기 명령.
- 찾기 단계는 정책마다 질문 하나라 `--agent-max-units` 로 묶지 않는다(`--agent-time-limit` 으로 묶는다).

# 국내 법 의무 지도

국내 법률·시행령·시행규칙·고시 206개를 읽고, 웹·앱 서비스를 만드는 쪽에 의무를 지우는 조항 가운데
**JS/TS 코드에 지켰는지가 드러나는 의무 795개**를 모았다(2026-10-14~15 조사). 방향 A 에서 의무 카탈로그의 원천이다.
법률 자문이 아니다.

- 사람이 읽는 판(법별 표, 우선순위 그림): Claude Docs "코드로 검사할 수 있는 국내 법 의무 지도"
  (https://claude.ai/code/artifact/5c51f5d6-0cd5-4311-8d36-f3167b678f67)
- 기계가 읽는 판: [duties.jsonl](duties.jsonl) — 한 줄에 의무 하나, 795줄
- 조사 원자료와 스크립트: `~/.cache/policypack-eval/lawmap-2026-10-14/` (merged.json sha256 앞 16자 `f6b986d3230ae0bf`)

## 숫자

| 탐지 방식 | 뜻 | 의무 수 |
|---|---|---|
| static | 한 파일·함수 안의 코드 모양으로 Semgrep 조건만으로 가릴 수 있다 | 11 |
| judge | 적용 신호는 보이지만 지켰는지는 뜻을 읽어야 한다 | 606 |
| flow | 여러 파일·화면·설정에 걸쳐 있다 | 178 |

누가 지는 의무인가: general(거의 모든 서비스) 94 · domain(위치·결제·광고·생성형 AI 같은 기능) 444 ·
sector(공공기관·금융회사 같은 지위) 257. kr-core 가 다루는 것은 10개(전부 6, 일부 4)다.
코드에 흔적이 없는 의무 277개와 중복·비의무로 뺀 26개는 이 파일에 없다.

## 필드

| 필드 | 뜻 |
|---|---|
| `id` | 의무 id (예: `pipa-22-2-1`). 정책이 이 id 를 가리킨다 |
| `law`, `article`, `quote`, `source_url`, `effective` | 법령명, 조문, 원문 인용(300자 이내), law.go.kr 링크, 받은 판의 시행일 |
| `duty_ko`, `addressee`, `trigger_ko` | 의무 한 줄, 의무를 지는 자, 코드에서 적용을 알아보는 신호 |
| `violation_shapes_ko`, `compliant_shapes_ko` | 어긴 코드·지킨 코드의 예 |
| `code_trace` | yes / partial |
| `detect`, `detect_why_ko` | static / judge / flow 와 그 이유 |
| `scope`, `scope_note` | general / domain / sector 와 그 기능·주체 |
| `krcore` | kr-core 가 다루는지 (yes / partial / no) |
| `confidence`, `status` | 조사자의 확신, 원문 대조 결과(confirmed / corrected / added-by-verifier) |
| `dev_freq` | 9/30 dev 저장소 20개에서 신호 정규식이 걸린 저장소·파일 수(흔함의 어림) |

## 주의

- 조문은 2026-10-14 현행판 기준이다. 정책으로 옮길 때 원문을 다시 받아 `_legal/` 에 해시로 고정한다.
- `dev_freq` 는 가입·쇼핑몰·메시지·생성형 AI 저장소를 골라 뽑은 표본의 값이라 금융·의료·위치는 낮게 나온다.
- 법령 조문은 저작권법 제7조에 따라 보호받지 않는 저작물이다.

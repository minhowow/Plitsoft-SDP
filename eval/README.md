# 평가 폴더 — 네 방식 비교 (12/1–12/7)

[PROTOCOL.md](PROTOCOL.md) 가 무엇을 어떻게 재는지 정한다. 이 폴더는 11/3 에 고정했고, 고정한 뒤에는 고치지 않는다.
고쳐야 하면 PROTOCOL.md 의 편차 표에 적는다. 요약은 [../docs/evaluation.md](../docs/evaluation.md) 에 있다.

| 파일 | 무엇 | 고정 |
|---|---|---|
| `PROTOCOL.md` | 분석 계획: 가설, 단위와 정답, 표본, 순서, 예측, 한계 | 11/9 |
| `guide/` | 라벨 기준서, 선별 낱말, 라벨러 프롬프트. 도구를 만드는 세션이 아닌 에이전트가 조문만 보고 썼다 | 11/9 |
| `seen.txt` | 이미 본 저장소 54곳. 후보에서 뺀다 | 11/9 |
| `ads-holdout.json` | 광고 보류분 26곳. 고정 전에 내려받거나 열지 않는다 | 11/9 |
| `scripts/candidates.py` | 후보 저장소 찾기(GitHub 검색, 메타데이터만). `fetch` 만 네트워크를 쓴다 | 11/9 |
| `scripts/beacon.py` | 공개 난수(drand) 받기. `fetch` 만 네트워크를 쓴다 | 11/9 |
| `scripts/draw.py` | 층별 추첨과 처리 대기열 | 11/9 |
| `scripts/units.py` | 라벨할 (시작 파일, 정책) 단위 뽑기. 도구의 판정과 무관하다 | 11/9 |
| `scripts/audit_sample.py` | 사람이 블라인드로 볼 감사 표본 | 11/9 |
| `scripts/compare.py` | 주 지표: 방식마다 쌍 단위 F1, 방식 사이 차이의 부트스트랩 구간 | 11/9 |
| `scripts/score.py` | 부 지표: 단위 단위 정밀도·재현율, 사람 감사, 엔진 미완 경고 | 11/9 |
| `scripts/manifest.py` | 고정한 파일의 SHA-256 목록 | 11/9 |
| 라벨러 실행 스크립트 | 라벨러 모델을 읽기 전용 도구와 함께 부른다 | 11/30 (아직 없음) |

## 고정하는 법

    python3 -I eval/scripts/manifest.py eval/PROTOCOL.md eval/README.md eval/guide eval/scripts \
        eval/seen.txt eval/ads-holdout.json > eval/freeze/H0-2026-11-03.txt
    git tag eval-freeze-2026-11-03

마지막 줄이 목록 전체의 해시다. 나중에 같은 명령을 다시 돌려 같은 값이 나오면 고정 뒤에 바뀐 파일이 없다.

## 지금까지 돌려 본 것 (11/3)

네트워크와 모델을 쓰는 것(`candidates.py fetch`, `beacon.py fetch`, 라벨러)은 돌리지 않았다. 나머지는 저장해 둔 자료로 돌려 봤다.

- `compare.py`, `score.py`: 9/30 test 라벨과 중간 평가 스캔. 단위 단위 값이 중간 보고서와 같다(정밀도 0.35, 독립 재현율
  0.19). 쌍 단위는 M1 F1 0.48, M2 0.43(저장소 18곳).
- `candidates.py build`: 10/6 에 받아 둔 검색 응답 셋. 이미 본 저장소가 빠지는 것을 확인했다.
- `draw.py`, `units.py`, `audit_sample.py`: 가짜 후보와 9/30 저장소 두 곳, `beacon.py round` 는 라운드 번호 계산만.

`candidates.py`·`draw.py`·`units.py`·`audit_sample.py`·`score.py` 는 10/7 초안(`~/.cache/policypack-eval/freeze-eval/`)을
방향 A 에 맞게 고친 것이다. 바뀐 점: 광고 질의를 빼고 보류분을 따로 둠, 처리 대기열, 단위를 시작 파일로, 여러 방식의 경고.

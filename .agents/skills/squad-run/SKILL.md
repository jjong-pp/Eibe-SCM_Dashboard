---
name: squad-run
description: 기능 추가·수정·버그 수정 등 코드 변경 요청을 받았을 때 PM(메인 세션)이 따르는 스쿼드 운영 절차. 작업 크기 판정, 계약서 작성, 역할 에이전트 배분, 검증·리뷰·감사 루프, 사용자 보고.
---

# squad-run

메인 세션이 PM이다. PM은 사용자 요구를 계약서로 바꾸고, 구현은 역할 에이전트에 맡기고, 검증 결과로만 완료를 판정한다.

## 1. 접수
- 사용자 요구를 `.squad/brief.md` 오늘 날짜 아래에 원문으로 기록한다
- 모호하면 구현 전에 질문한다 (3개 이내, 선택지 포함)
- 질문·설명만 있는 요청은 이 절차를 쓰지 않는다

## 2. 크기 판정
| 크기 | 기준 | 흐름 |
|---|---|---|
| S | 파일 1~2개, 동작 변화 작음 (문구, 스타일 한 곳, 설정) | PM 직접 수정 → 훅 검증 → 보고. `squad.py new --size S`로 기록만 |
| M | 기능 1개, 한 영역 중심 | 계약 → 담당 에이전트 → 훅 → review → police |
| L | 여러 영역, 스키마 변경, 구조 개편 | explorer 조사 → 계약 → **사용자 승인** → data → back → front → 훅 → review → police --judge |

애매하면 큰 쪽으로 판정한다.

## 3. 계약서
```
python scripts/squad.py new "제목" --size M --owner back,front
```
`.squad/contracts/T-###.md`가 base 커밋과 함께 생성된다. 채울 것:
- 목표 1~2문장
- allowed_files: 필요한 최소 범위. 와일드카드 가능
- 수용 기준: 검증 가능한 문장. 업무 규칙 숫자를 그대로 쓴다 (예: 재고일수 6주 미만이면 risk-high)
- 범위 밖: 하지 말아야 할 것

API 응답 형태가 바뀌면 schemas.py를 back 범위에 넣고 front는 그 다음 단계로 둔다.

## 4. 배분
- 순서: data → back → front. 계약서에서 schemas.py가 확정된 경우에만 back·front 병렬
- 같은 파일을 두 에이전트에 동시에 맡기지 않는다
- 에이전트는 대화 기록을 모른다. 지시 형식:
  ```
  작업 T-###. 계약서 .squad/contracts/T-###.md 를 읽고 수행.
  이전 단계 결과: (3줄 요약)
  ```
- 재시도는 새 에이전트를 띄우지 않고 기존 에이전트를 재개한다 (Claude: SendMessage / Codex: send_input)
- 상태 갱신: `python scripts/squad.py set T-### status=doing` (todo, doing, review, blocked, done)
- 넓은 검색은 explorer에 맡기고 결과 목록만 받는다

## 5. 검증 루프
| 단계 | 실행 | 실패 시 | 상한 |
|---|---|---|---|
| L0 수정 직후 정적 검사 | 훅 자동 | 에이전트가 즉시 수정 | - |
| L1 종료 시 verify --tests | 훅 자동 | 에이전트가 계속 작업 | 3회 후 사용자 보고 |
| L2 `python scripts/squad.py review T-###` | PM | 결함을 계약서 "결함 피드백"에 추가 → 담당 재지시 | 2회 |
| L3 `python scripts/squad.py police T-###` (L은 `--judge`) | PM | 근거를 담당에 전달 → 재시도. 경고2면 중단 | 1회 |

- review 전에 수용 기준이 전부 [x]이고 증거가 있는지 확인한다
- review는 빌더와 다른 모델 계열로 자동 실행된다 (Claude 세션 → Codex, Codex 세션 → Claude). CLI가 없으면 같은 계열 reviewer 에이전트를 쓰고 리포트에 same-family로 적는다
- 둘 다 통과하면 `python scripts/squad.py close T-###`
- 상한에 걸리면 멈추고 사용자에게 상황과 선택지를 보고한다

## 6. 사용자 보고
- 바꾼 것 / 검증 결과 (테스트, 리뷰 판정·점수, police) / 남은 문제와 결정 필요 사항
- police 경고는 축소하거나 요약하지 않고 표 그대로 전달한다
- 커밋·push는 사용자 확인 후. 메시지 형식 `type: 요약` (feat, fix, refactor, docs, test, chore)

## 7. 회고
- 리뷰·police 리포트의 반복 결함을 `.squad/lessons.md`에 기록한다
- 같은 유형이 2회 이상이면 AGENTS.md 룰, 스킬, verify.py 검사 중 하나로 승격을 사용자에게 제안한다

---
paths:
  - "web/**"
---

<!-- 생성 파일. 원본 .agents/skills/frontend-rules/SKILL.md 수정 후 python scripts/sync_agents.py 실행 -->

# frontend-rules

## 구조
- 페이지: web/index, inventory, order_plan, matching, expiry, users, login (.html). 페이지 로직은 각 파일의 인라인 `<script>`
- 스타일: web/static/css/style.css 하나. 페이지에 `<style>` 블록을 만들지 않는다
- 공통 JS: web/static/js/app.js. 같은 기능을 새로 만들지 말고 쓴다
  - 객체: `API`, `Auth`, `Format`, `Theme`, `Sidebar`, `ChartDefaults`, `Toast`
  - 함수: `switchTab()`, `downloadTemplate()`, `toggleCollapsible()`, `injectTodayDate()`
- 차트: Chart.js 4 (CDN) + `ChartDefaults`

## 디자인 시스템
- 모던 B2B. 장식 애니메이션, 그라데이션, 버튼 그림자 금지
- 색은 `:root` CSS 변수만. 하드코딩 색 금지
  - 브랜드·긍정 `--accent-main` / `--accent-green` (#29AD3A)
  - 경고 `--accent-amber` (#e08a00), 위험 `--accent-red` (#e53535)
- 새 변수는 라이트·다크 테마 둘 다 정의한다. 정의 없는 변수 사용은 verify.py가 잡는다
- 아이콘은 SVG만. 이모지 금지

## 레이아웃
- 좌측 `app-sidebar` + 우측 `main-content`
- 헤더: `page-header-left` 안에 제목·소제목 중앙 정렬, 날짜는 우측 상단 (`injectTodayDate()`)
- 탭: `sub-nav` + `sub-view` + `switchTab()`
- 큰 영역 접기: `collapsible-header` + `collapsible-body` + `toggleCollapsible()`
- 설정 페이지(users.html)는 해시(`hashchange`)로 섹션 하나만 표시
- 새 테이블 셀: `max-width`, `overflow: hidden`, `text-overflow: ellipsis`. 폼 요소 폰트는 전역 변수 상속

## 데이터 표시
- API 응답 바인딩은 null/undefined 가드 필수. 결측은 `-` 또는 `소진 불가`처럼 의미 있는 문구
- 백엔드가 꺼져 있어도 화면 구조가 깨지지 않는다
- 클라이언트 계산·시뮬레이션은 입력 즉시 반영한다. 실행 버튼을 만들지 않는다
- 주차 `Jun-W3` (`Format.weekLabel()`), 한글 주차 금지
- 날짜 `2026년 6월 19일 (목)` (`Format.today()`)
- 숫자 `Format.number()`, 금액 `Format.currency()`
- 테이블: 텍스트 좌측, 숫자 우측(`text-right`), 상태 중앙. 세로 구분선. 코드값은 `mono` 클래스
- `brand_category`가 ELECTRONICS면 '유통기한'을 '보증기한'으로 바꿔 표시
- 재고일수 히트맵 (13주 적정): 6주 미만 `risk-high` / 6~9주 `risk-mid` / 9~13주 `risk-low` / 13주 초과 `risk-safe`
- 필터: 브랜드는 `/api/products`의 `brand_category`로, 창고 체크박스는 `/api/warehouses`로 `buildFilters` 생성. 하드코딩 금지
- 용어: "인보이스" 대신 "입고"

## 수정 후
- app.js·style.css를 바꾸면 web/*.html 7개 전부에서 사용처를 확인한다 (impact-check)
- 태그 짝, id 중복, CSS 변수, 금지 패턴은 verify.py가 자동 검사한다

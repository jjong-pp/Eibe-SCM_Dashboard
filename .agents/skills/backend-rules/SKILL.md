---
name: backend-rules
description: app/routers, app/core, app/schemas.py, app/main.py, tests를 수정할 때 따르는 백엔드 규칙. API 구조, 예측·원가 로직, null 처리, 성능, 테스트 작성법.
---

# backend-rules

## 구조
- app/main.py: 앱 생성, lifespan(테이블 생성·admin 계정·스케줄러), 전역 예외 처리기, 라우터 등록
- app/routers/: auth, users, master(기준 정보), pipeline(발주·생산·입고), inventory(재고·유통기한·발주 계획·엑셀·이관), system(헬스·스냅샷), views(HTML 파일 서빙)
- app/core/: forecasting(예측), excel_parser(템플릿·파싱), auth(JWT·bcrypt), snapshot(data 담당)
- app/schemas.py: Pydantic v2 응답·요청 모델. 응답 필드 변경은 front 영향이므로 계약서에 적는다

## 규칙
- 프론트와는 API로만 연결한다. 서버 템플릿 렌더링 금지 (views는 FileResponse만)
- 예측은 사칙연산 통계(평탄화 평균 등)만. ML 라이브러리 금지
- 자산·원가는 `InboundDB.payment_amount_krw`(실결제 원화) 기준. `InvoiceDB`는 폐기됨
- 발주 계획은 리드타임을 고려해 6개월(24주) 뒤 도착분 기준
- Optional 필드 가드: `if product.pack_qty_per_tu and product.pack_qty_per_tu > 0`
- 날짜 문자열은 시간 부분을 떼고 파싱: `value.split(" ")[0]`
- 엑셀 파싱은 `parse_excel_file(file_bytes, template_type)`. 필수 컬럼은 최소로 둔다
- DB 세션은 `Depends(get_db)`. 쓰기 실패 시 rollback
- 인증 API는 `Depends(get_current_user)`, 관리자 API는 `get_current_admin`
- 목록 API는 N+1 쿼리를 피한다 (joinedload/selectinload 또는 집계 쿼리)
- 상수(상태값 목록 등)는 모델 제약 조건과 같은 값으로 모듈 상단에 선언한다

## 성능
- 목록·요약 API를 바꾸면 시드 데이터 기준 응답 시간을 측정해 증거로 적는다

## 테스트
- tests/는 임시 DB + 고정 시드 (conftest.py). 운영 DB를 쓰지 않는다
- 새 GET 라우트는 tests/test_smoke.py 목록에 추가한다
- 계산 로직 변경은 입력·기대값이 고정된 단위 테스트를 추가한다
- 테스트 삭제·skip·assert 제거 금지

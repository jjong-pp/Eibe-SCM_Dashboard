---
name: impact-check
description: 함수·변수·CSS 클래스·DOM id·API 필드·DB 컬럼의 이름이나 동작을 바꾸기 전에 전체 참조를 찾는 절차. 수정 전 영향 범위 확인이 필요할 때 사용.
---

# impact-check

1. 바꿀 심볼 목록을 만든다 (이름, 종류, 바꿀 내용)
2. 종류별로 검색한다. venv/, __pycache__/, data/, portfolio/ 제외
   | 종류 | 찾을 곳 |
   |---|---|
   | Python 함수·상수 | app/, tests/, seed_data.py, scripts/ |
   | API 응답 필드 | app/schemas.py, app/routers/, web/*.html의 `.필드명` 사용처 |
   | DB 컬럼 | app/models.py, app/schemas.py, app/routers/, app/core/, seed_data.py, excel_parser 템플릿 컬럼 |
   | CSS 클래스 | style.css 정의, web/*.html `class=`, app.js `classList`·`className`·문자열 템플릿 |
   | DOM id | web/*.html `id=`, `getElementById`, `querySelector('#...')` |
   | app.js 함수·객체 | web/*.html 7개 전부 |
3. 결과를 `파일:줄 — 사용 방식` 목록으로 정리한다
4. 목록 전부를 같은 작업에서 고친다. allowed_files 밖이면 고치지 말고 PM에 목록을 넘긴다
5. 끝난 뒤 같은 검색을 다시 돌려 옛 이름이 남지 않았는지 확인한다

---
name: dev-server
description: 개발 서버 기동·재시작, 샘플 데이터 시드, API 무응답(포트 점유 좀비 프로세스) 해결 절차.
---

# dev-server

## 기동
- Windows: `start_server.bat` (venv가 없으면 생성하고 의존성 설치)
- 직접: `venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload`
- 접속 http://localhost:8000, 기본 계정 admin/admin
- 개발 의존성(pytest, ruff): `venv\Scripts\python -m pip install -r requirements-dev.txt`

## 시드
- `seed_data.py`는 기존 거래 데이터를 지우고 다시 채운다. 운영 DB에 돌리기 전 사용자 확인
- 별도 DB로: PowerShell `$env:SCM_DB_PATH="data\dev.db"; venv\Scripts\python seed_data.py`
- QA용 고정 시드 서버: `python scripts/squad.py qa-server start` / `stop` (포트 8765, .squad/state/qa.db)

## API 무응답
코드를 보기 전에 서버 프로세스부터 확인한다. 비정상 종료된 uvicorn과 스케줄러 스레드가 포트를 잡고 있던 이력이 있다.
1. `netstat -ano | findstr :8000` 으로 PID 확인
2. 해당 PID가 python/uvicorn인지 확인 후 `taskkill /PID <pid> /F`
3. 재시작 후 `/api/health` 확인

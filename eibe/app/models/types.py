"""
공용 컬럼 타입.

금액 정밀도가 왜 이 값인지:

SQLite 에는 네이티브 DECIMAL 이 없어 SQLAlchemy 가 float 를 경유해 저장한다.
float64 는 2^53(약 9.007e15)까지의 정수만 정확히 표현하므로, 유효자릿수
(정수부 + 소수부)가 15를 넘으면 값이 조용히 반올림된다.

    Numeric(18, 2) 에 999999999999999.99 저장 → 1000000000000000.00 으로 손실

PostgreSQL 은 임의 정밀도라 이 제약이 없지만, 같은 코드가 양쪽에서 동일하게
동작해야 하므로 낮은 쪽에 맞춘다. 아래 한도는 실제 업무 금액(원화 억~조 단위)을
한참 웃돌기 때문에 실용적인 손해가 없다.
"""

from __future__ import annotations

from sqlalchemy import Numeric

# 유효자릿수 15 = float64 가 정확히 담을 수 있는 한계
_SAFE_SIGNIFICANT_DIGITS = 15

#: 금액. 최대 9,999,999,999,999.99 (약 10조)
Money = Numeric(_SAFE_SIGNIFICANT_DIGITS, 2)

#: 단가. 소수점 4자리까지 (외화 단가에 필요). 최대 9,999,999,999.9999
UnitPrice = Numeric(_SAFE_SIGNIFICANT_DIGITS - 1, 4)

#: 환율·비율. 최대 99,999,999.9999
Rate = Numeric(12, 4)

#: 백분율. 최대 999.999
Percent = Numeric(6, 3)

__all__ = ["Money", "Percent", "Rate", "UnitPrice"]

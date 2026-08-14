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

from enum import StrEnum

from sqlalchemy import Numeric, String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

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


class EnumStr(TypeDecorator[StrEnum]):
    """StrEnum 을 VARCHAR 로 저장하되 **읽을 때 다시 enum 으로 되돌린다.**

    `mapped_column(String(16))` 에 `Mapped[SomeEnum]` 을 달아도 SQLAlchemy 는
    타입 힌트를 강제하지 않는다. 저장은 되지만 조회하면 그냥 `str` 이 나오고,
    enum 에 붙여둔 프로퍼티를 부르는 순간 터진다.

        product.brand.category.expiry_label
        AttributeError: 'str' object has no attribute 'expiry_label'

    같은 세션에서 방금 만든 객체는 진짜 enum 이라 테스트에서는 통과하고,
    DB 에서 다시 읽는 실제 경로에서만 실패한다. 그래서 읽는 쪽에서 매번
    `BrandCategory(value)` 로 감싸는 대신 타입이 책임지게 한다.

    네이티브 ENUM 을 쓰지 않는 이유는 그대로다 (P-09): Postgres 네이티브
    ENUM 은 값 추가에 ALTER TYPE 이 필요하고 SQLite 에는 대응 개념이 없다.
    저장 형태는 여전히 VARCHAR 이므로 CHECK 제약과 마이그레이션이 그대로다.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[StrEnum], length: int = 16) -> None:
        super().__init__(length=length)
        self.enum_cls = enum_cls

    def process_bind_param(
        self, value: StrEnum | str | None, dialect: Dialect
    ) -> str | None:
        if value is None:
            return None
        # 알 수 없는 값은 여기서 막는다. DB CHECK 제약까지 가기 전에 잡힌다.
        return self.enum_cls(value).value

    def process_result_value(
        self, value: str | None, dialect: Dialect
    ) -> StrEnum | None:
        return None if value is None else self.enum_cls(value)


__all__ = ["EnumStr", "Money", "Percent", "Rate", "UnitPrice"]

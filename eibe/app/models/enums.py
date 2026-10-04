"""
도메인 열거형.

Postgres 네이티브 ENUM 대신 문자열 + CHECK 제약으로 저장한다. 네이티브
ENUM 은 값을 추가할 때 ALTER TYPE 이 필요해 마이그레이션이 까다롭고,
SQLite 에는 대응 개념이 없어 방언 간 이식성이 떨어진다.
"""

from __future__ import annotations

from enum import StrEnum


class BrandCategory(StrEnum):
    """브랜드 성격. 화면 문구가 여기에 따라 바뀐다.

    ELECTRONICS 는 '유통기한' 대신 '보증기한'으로 표기한다.
    """

    FOOD = "FOOD"
    ELECTRONICS = "ELECTRONICS"

    @property
    def expiry_label(self) -> str:
        """기한 컬럼에 붙일 이름. 화면마다 따로 분기하지 않도록 여기서 정한다."""
        return "보증기한" if self is BrandCategory.ELECTRONICS else "유통기한"


class WarehouseType(StrEnum):
    HUB = "HUB"          # 용인 메인창고 — 이관의 출발점
    ONLINE = "ONLINE"    # 온라인 풀필먼트
    OFFLINE = "OFFLINE"  # 오프라인 풀필먼트
    BUYOUT = "BUYOUT"    # 바이아웃


class InboundStatus(StrEnum):
    """입고 파이프라인 진행 단계. 순서가 곧 진행도다."""

    DEPARTED = "생산국출발"
    IN_TRANSIT = "해상운송중"
    ARRIVED_KR = "한국도착"
    CUSTOMS = "통관중"
    SCHEDULING = "입고일선정중"
    RECEIVED = "입고완료"

    @property
    def order(self) -> int:
        return INBOUND_STATUS_ORDER[self]


INBOUND_STATUS_ORDER: dict[InboundStatus, int] = {
    status: index for index, status in enumerate(InboundStatus)
}


class OutflowType(StrEnum):
    SALES = "SALES"        # 판매로 인한 출고
    LOSS = "LOSS"          # 파손·폐기 등 감모
    TRANSFER = "TRANSFER"  # 창고 간 이관


class MetricSource(StrEnum):
    """주차 집계값의 출처.

    DERIVED  — 판매 원장/재고 스냅샷에서 재계산된 값. 언제든 다시 만들 수 있다.
    IMPORTED — 엑셀로 직접 올린 값. 재계산해도 덮어쓰지 않는다.
    """

    DERIVED = "DERIVED"
    IMPORTED = "IMPORTED"


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"          # 수정 중
    CONFIRMED = "CONFIRMED"  # 확정


def check_in(column: str, enum_cls: type[StrEnum]) -> str:
    """CHECK 제약용 SQL 조각을 만든다. 값 목록을 손으로 중복 작성하지 않는다."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"

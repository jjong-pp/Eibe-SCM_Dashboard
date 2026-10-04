"""
EIBE SCM — 3NF 관계형 테이블 스키마 정의
모든 '마스터' 용어를 'DB'로 교체
"""

from sqlalchemy import (
    Column, Integer, Text, Float, Boolean, ForeignKey,
    CheckConstraint, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database import Base

VALID_INBOUND_STATUSES = ["생산국출발", "해상운송중", "한국도착", "통관중", "입고일선정중", "입고완료"]

# ═══════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════

class UserAccount(Base):
    """사용자 계정"""
    __tablename__ = "USER_ACCOUNT"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    name = Column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('ADMIN', 'OPERATOR')", name="chk_user_role"),
    )


class SystemSnapshot(Base):
    """시스템 스냅샷 — 백업 관리"""
    __tablename__ = "SYSTEM_SNAPSHOT"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_path = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("USER_ACCOUNT.id"), nullable=True)
    is_auto = Column(Boolean, default=True)

    creator = relationship("UserAccount")


# ═══════════════════════════════════════════════════════════════════════
# 기준 정보 DB
# ═══════════════════════════════════════════════════════════════════════

class ProductDB(Base):
    """품목 DB — 품목코드가 비즈니스 ID (수정 불가)"""
    __tablename__ = "PRODUCT_DB"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_code = Column(Text, unique=True, nullable=False)       # 품목코드 (수정 불가, ID)
    product_name = Column(Text, nullable=False)                    # 품목명
    brand_category = Column(Text, nullable=False, default="FOOD")  # 브랜드/카테고리
    pack_qty_per_tu = Column(Integer, nullable=False, default=24)  # 카툰당 입수량
    currency_unit = Column(Text, nullable=False, default="USD")    # 환율단위 (USD, EUR 등)
    purchase_price = Column(Float, nullable=False, default=0)      # 매입가 (외화 기준)

    # Relationships
    orders = relationship("OrderDB", back_populates="product")
    productions = relationship("ProductionDB", back_populates="product")
    inbounds = relationship("InboundDB", back_populates="product")
    outflow_histories = relationship("OutflowHistory", back_populates="product")
    order_plans = relationship("MonthlyOrderPlan", back_populates="product")


class WarehouseDB(Base):
    """창고 DB — 거점코드 자동증가(노출 안 함), 창고명 수정 불가"""
    __tablename__ = "WAREHOUSE_DB"

    id = Column(Integer, primary_key=True, autoincrement=True)     # 거점코드 (자동, 숨김)
    warehouse_name = Column(Text, unique=True, nullable=False)     # 창고명 (수정 불가)
    warehouse_type = Column(Text, nullable=False, default="ONLINE")
    allowed_expiry_days = Column(Integer, default=90)              # 허용 유통기한(일)
    moq = Column(Integer, default=0)                               # 이관 MOQ

    __table_args__ = (
        CheckConstraint(
            "warehouse_type IN ('ONLINE', 'OFFLINE', 'BUYOUT')",
            name="chk_wh_type",
        ),
    )

    snapshots = relationship("InventorySnapshot", back_populates="warehouse")
    outflow_histories = relationship("OutflowHistory", back_populates="warehouse")
    departure_costs = relationship("LogisticsCostDB", foreign_keys="LogisticsCostDB.departure_wh_id", back_populates="departure_wh")
    arrival_costs = relationship("LogisticsCostDB", foreign_keys="LogisticsCostDB.arrival_wh_id", back_populates="arrival_wh")


class WarehouseProductMOQ(Base):
    """창고-품목별 이관 MOQ 오버라이드"""
    __tablename__ = "WAREHOUSE_PRODUCT_MOQ"

    id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_id = Column(Integer, ForeignKey("WAREHOUSE_DB.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("PRODUCT_DB.id"), nullable=False)
    transfer_moq = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("warehouse_id", "product_id", name="uq_wh_product_moq"),
    )

    warehouse = relationship("WarehouseDB", backref="product_moqs_list")
    product = relationship("ProductDB", backref="warehouse_moqs_list")


class LogisticsCostDB(Base):
    """구간별 물류비 DB"""
    __tablename__ = "LOGISTICS_COST_DB"

    departure_wh_id = Column(Integer, ForeignKey("WAREHOUSE_DB.id"), primary_key=True)
    arrival_wh_id = Column(Integer, ForeignKey("WAREHOUSE_DB.id"), primary_key=True)
    cost_per_tu = Column(Integer, nullable=False)

    departure_wh = relationship("WarehouseDB", foreign_keys=[departure_wh_id], back_populates="departure_costs")
    arrival_wh = relationship("WarehouseDB", foreign_keys=[arrival_wh_id], back_populates="arrival_costs")


# ═══════════════════════════════════════════════════════════════════════
# 입고 파이프라인 (발주 → 생산 → 인보이스 → 입고)
# ═══════════════════════════════════════════════════════════════════════

class OrderDB(Base):
    """발주 DB"""
    __tablename__ = "ORDER_DB"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_month = Column(Text, nullable=False)                     # 발주월 (YYYY-MM)
    product_code = Column(Text, ForeignKey("PRODUCT_DB.product_code"), nullable=False)
    order_qty = Column(Integer, nullable=False)                    # 발주수량 (캔)
    created_at = Column(Text)

    product = relationship("ProductDB", back_populates="orders")
    matched_productions = relationship("ProductionDB", back_populates="matched_order")


class ProductionDB(Base):
    """생산 DB"""
    __tablename__ = "PRODUCTION_DB"

    id = Column(Integer, primary_key=True, autoincrement=True)
    purchase_code = Column(Text, nullable=False)                   # 구매코드
    production_code = Column(Text, nullable=False)                 # 생산코드
    order_month = Column(Text)                                     # 발주월
    production_qty = Column(Integer, nullable=False)               # 생산수량
    product_code = Column(Text, ForeignKey("PRODUCT_DB.product_code"), nullable=False)
    matched_order_id = Column(Integer, ForeignKey("ORDER_DB.id"), nullable=True)
    created_at = Column(Text)

    product = relationship("ProductDB", back_populates="productions")
    matched_order = relationship("OrderDB", back_populates="matched_productions")
    matched_inbounds = relationship("InboundDB", back_populates="matched_production")



class InboundDB(Base):
    """입고 DB (인보이스 기능 통합)"""
    __tablename__ = "INBOUND_DB"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_no = Column(Text)                                      # 인보이스번호
    bl_no = Column(Text)                                           # BL번호
    mapping_value = Column(Text)                                   # 매핑값
    purchase_code = Column(Text)                                   # 구매코드
    production_code = Column(Text)                                 # 생산코드
    shipping_date = Column(Text)                                   # 선적일
    korea_arrival_date = Column(Text)                              # 한국도착일
    eta = Column(Text)                                             # ETA
    manufacture_date = Column(Text)                                # 제조일자
    expiry_date = Column(Text)                                     # 유통기한
    carton_qty = Column(Integer)                                   # 카툰수
    can_qty = Column(Integer)                                      # 캔수
    unit_price = Column(Float)                                     # 단가
    total_price = Column(Float)                                    # 총단가
    payment_date = Column(Text)                                    # 결제일
    invoice_date = Column(Text)                                    # 인보이스 발행일
    exchange_rate = Column(Float)                                  # 결제환율
    payment_amount_krw = Column(Integer)                           # 결제금액(원화)
    arrival_wh_id = Column(Integer, ForeignKey("WAREHOUSE_DB.id"), nullable=True) # 도착창고
    matched_production_id = Column(Integer, ForeignKey("PRODUCTION_DB.id"), nullable=True)
    product_code = Column(Text, ForeignKey("PRODUCT_DB.product_code"), nullable=True)
    status = Column(Text, default="생산국출발")
    created_at = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('생산국출발', '해상운송중', '한국도착', '통관중', '입고일선정중', '입고완료')",
            name="chk_inbound_status",
        ),
    )

    product = relationship("ProductDB", back_populates="inbounds")
    matched_production = relationship("ProductionDB", back_populates="matched_inbounds")
    arrival_wh = relationship("WarehouseDB")


# ═══════════════════════════════════════════════════════════════════════
# 재고 및 실적
# ═══════════════════════════════════════════════════════════════════════

class InventorySnapshot(Base):
    """현재고 스냅샷 — 시점별 재고 기록"""
    __tablename__ = "INVENTORY_SNAPSHOT"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(Text, nullable=False)                   # 스냅샷 일자
    warehouse_id = Column(Integer, ForeignKey("WAREHOUSE_DB.id"), nullable=True)
    warehouse_name = Column(Text)                                  # 창고이름 (비정규화)
    product_name = Column(Text)                                    # 품목명
    product_code = Column(Text)                                    # 품목코드
    expiry_date = Column(Text)                                     # 유통기한
    qty_cans = Column(Integer, nullable=False, default=0)          # 수량 (캔)
    updated_at = Column(Text)                                      # 업데이트 일시

    warehouse = relationship("WarehouseDB", back_populates="snapshots")


class OutflowHistory(Base):
    """출고 이력 — 주차별 재고 소멸 로그"""
    __tablename__ = "OUTFLOW_HISTORY"

    outflow_id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_id = Column(Integer, ForeignKey("WAREHOUSE_DB.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("PRODUCT_DB.id"), nullable=False)
    base_date = Column(Text, nullable=False)
    beginning_inventory = Column(Integer, nullable=False)
    ending_inventory = Column(Integer, nullable=False)
    simple_outflow_qty = Column(Integer, nullable=False)
    outflow_type = Column(Text, default="SALES")

    __table_args__ = (
        CheckConstraint("outflow_type IN ('SALES', 'LOSS', 'TRANSFER')", name="chk_outflow_type"),
    )

    warehouse = relationship("WarehouseDB", back_populates="outflow_histories")
    product = relationship("ProductDB", back_populates="outflow_histories")


class MonthlyOrderPlan(Base):
    """월별 발주 계획 (시뮬레이션)"""
    __tablename__ = "MONTHLY_ORDER_PLAN"

    plan_id = Column(Integer, primary_key=True, autoincrement=True)
    target_month = Column(Text, nullable=False)
    arrival_month = Column(Text, nullable=True)
    product_id = Column(Integer, ForeignKey("PRODUCT_DB.id"), nullable=False)
    system_suggested_qty = Column(Integer, nullable=False, default=0)
    user_modified_qty = Column(Integer, nullable=False, default=0)
    version = Column(Integer, default=1)
    updated_at = Column(Text)

    __table_args__ = (
        UniqueConstraint("target_month", "product_id", name="uq_month_product"),
    )

    product = relationship("ProductDB", back_populates="order_plans")


class SalesHistory(Base):
    """판매 실적 — 주차별 판매량"""
    __tablename__ = "SALES_HISTORY"

    sales_id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_id = Column(Integer, ForeignKey("WAREHOUSE_DB.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("PRODUCT_DB.id"), nullable=False)
    base_date = Column(Text, nullable=False)
    sales_qty = Column(Integer, nullable=False)
    created_at = Column(Text)

    warehouse = relationship("WarehouseDB")
    product = relationship("ProductDB")

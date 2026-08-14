"""
개발·테스트용 시드 데이터.

구 seed_data.py 를 대체한다. 두 가지가 달라졌다:
  1. production 에서는 실행을 거부한다. 알려진 비밀번호 계정을 운영 DB 에
     심는 사고를 구조적으로 막는다.
  2. 멱등하다. 몇 번을 돌려도 같은 상태가 되므로 반복 실행이 안전하다.

    python -m scripts.seed_dev            # 계정 + 마스터 + 샘플 실적
    python -m scripts.seed_dev --accounts-only
    python -m scripts.seed_dev --reset    # 기존 데이터를 지우고 다시
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dates import IsoWeek, iso_week_of
from app.core.security import hash_password
from app.database import SessionLocal
from app.models.auth import Role, User
from app.models.enums import BrandCategory, InboundStatus, MetricSource, WarehouseType
from app.models.master import Brand, Channel, Product, ProductAlias, Warehouse
from app.models.metrics import WeeklyMetric
from app.models.sales import Promotion, SalesOrder
from app.models.scm import Inbound, InventorySnapshot
from app.services.derive import (
    apply_inventory_flow,
    rebuild_weekly_metrics,
    resolve_sales_mappings,
)

# 개발 환경 전용 비밀번호. 운영에서는 이 스크립트 자체가 실행되지 않는다.
DEV_PASSWORD = "dev-password-1234"

DEV_ACCOUNTS = [
    ("admin", "개발 관리자", Role.ADMIN),
    ("operator", "개발 운영자", Role.OPERATOR),
    ("viewer", "개발 조회자", Role.VIEWER),
]

WAREHOUSES = [
    ("용인 메인", WarehouseType.HUB),
    ("온라인 FFC", WarehouseType.ONLINE),
    ("오프라인 FFC", WarehouseType.OFFLINE),
    ("쿠팡 FFC", WarehouseType.ONLINE),
    ("바이아웃", WarehouseType.BUYOUT),
]

CHANNELS = [
    ("쿠팡", "온라인", "쿠팡 FFC", True),
    ("네이버", "온라인", "온라인 FFC", True),
    ("자사몰", "온라인", "온라인 FFC", True),
    ("이마트", "오프라인", "오프라인 FFC", True),
    ("홈쇼핑", "오프라인", "오프라인 FFC", False),
]

PRODUCTS = [
    ("H12PRO", "드리미 H12 Pro 무선청소기", 1, "289.0000"),
    ("L10ULTRA", "드리미 L10 Ultra 로봇청소기", 1, "512.0000"),
    ("X30", "드리미 X30 로봇청소기", 1, "738.5000"),
]

# 판매 원장에 실제로 찍히는 표기 흔들림 — ProductAlias 가 흡수한다.
ALIASES = [
    ("드리미 H12 Pro", "H12PRO", "H12 시리즈"),
    ("H12PRO 무선청소기", "H12PRO", "H12 시리즈"),
    ("드리미 L10 울트라", "L10ULTRA", "L10 시리즈"),
    ("L10 Ultra", "L10ULTRA", "L10 시리즈"),
    ("드리미 X30", "X30", "X30 시리즈"),
]

# 행사. (채널, 원본 제품명, 구좌, 행사명, 기간(일)) 형태다.
#
# 기간을 '몇 주 전'으로 못박지 않고 **실제 판매가 있는 날에 맞춰 붙인다.**
# 처음에는 고정 오프셋으로 만들었는데, 판매가 주당 1건씩 임의의 요일에
# 찍히다 보니 네 건 중 세 건이 행사 기간 안에 판매 0으로 잡혔다. 그러면
# 리프트가 전부 -100% 라 행사 ROI 화면을 검증할 수 없다.
PROMOTIONS = [
    ("쿠팡", "드리미 H12 Pro", "메인 배너", "쿠팡 여름 특가", 7),
    ("이마트", "드리미 X30", "행사 매대", "이마트 로봇청소기 페어", 5),
    ("네이버", "드리미 L10 울트라", "럭키투데이", "네이버 리빙위크", 10),
]

# 아직 시작하지 않은 행사. 등록만 해두는 것이 실제 운영 형태이고,
# '시작 전'과 '진행했는데 안 팔림'을 화면이 구분하는지 확인하는 데 쓴다.
UPCOMING_PROMOTION = ("자사몰", "", "전체 기획전", "자사몰 브랜드데이", 4)


def _guard_environment() -> None:
    if settings.is_production:
        print(
            "production 환경에서는 시드를 실행할 수 없습니다.\n"
            "알려진 비밀번호의 계정이 운영 DB 에 들어가는 것을 막기 위한 제한입니다.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def seed_accounts(db: Session) -> None:
    for username, name, role in DEV_ACCOUNTS:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(DEV_PASSWORD),
                    name=name,
                    email=f"{username}@eibe.co.kr",
                    role=role,
                )
            )
        else:
            # 비밀번호가 바뀌었을 수 있으므로 알려진 값으로 되돌린다.
            user.password_hash = hash_password(DEV_PASSWORD)
            user.role = role
            user.is_active = True
    db.commit()


def seed_master(db: Session) -> Brand:
    brand = db.scalar(select(Brand).where(Brand.slug == "dreame"))
    if brand is None:
        brand = Brand(name="드리미", slug="dreame", category=BrandCategory.ELECTRONICS)
        db.add(brand)
        db.flush()

    warehouses: dict[str, Warehouse] = {}
    for name, wh_type in WAREHOUSES:
        warehouse = db.scalar(select(Warehouse).where(Warehouse.name == name))
        if warehouse is None:
            warehouse = Warehouse(name=name, type=wh_type)
            db.add(warehouse)
            db.flush()
        warehouses[name] = warehouse

    for name, group, warehouse_name, is_major in CHANNELS:
        channel = db.scalar(select(Channel).where(Channel.name == name))
        if channel is None:
            channel = Channel(name=name)
            db.add(channel)
        channel.channel_group = group
        channel.warehouse_id = warehouses[warehouse_name].id
        channel.is_major = is_major

    products: dict[str, Product] = {}
    for code, name, pack_qty, price in PRODUCTS:
        product = db.scalar(select(Product).where(Product.product_code == code))
        if product is None:
            product = Product(product_code=code, name=name, brand_id=brand.id)
            db.add(product)
            db.flush()
        product.name = name
        product.pack_qty_per_tu = pack_qty
        product.purchase_price = Decimal(price)
        products[code] = product

    for source_name, product_code, lineup in ALIASES:
        alias = db.scalar(
            select(ProductAlias).where(ProductAlias.source_name == source_name)
        )
        if alias is None:
            alias = ProductAlias(source_name=source_name)
            db.add(alias)
        alias.product_id = products[product_code].id
        alias.lineup_name = lineup

    db.commit()
    return brand


def seed_activity(db: Session, brand: Brand, weeks: int = 26) -> None:
    """최근 N주간의 판매·재고·입고 실적.

    난수 시드를 고정해 실행할 때마다 같은 데이터가 나오게 한다. 예측 결과가
    실행마다 달라지면 화면을 검증할 수 없다.
    """
    rng = random.Random(20260813)

    products = list(db.scalars(select(Product)))
    channels = list(db.scalars(select(Channel).where(Channel.warehouse_id.is_not(None))))
    hub = db.scalar(select(Warehouse).where(Warehouse.type == WarehouseType.HUB))
    if not products or not channels or hub is None:
        return

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    # ── 판매 원장 ────────────────────────────────────────────────────
    # 이미 있으면 건너뛴다. 그러지 않으면 실행할 때마다 주문이 배로 쌓인다.
    # 다시 만들려면 --reset 을 쓴다.
    if db.scalar(select(SalesOrder).limit(1)) is None:
        base_demand = {p.product_code: rng.randint(40, 120) for p in products}
        alias_by_product = {
            p.id: list(
                db.scalars(select(ProductAlias).where(ProductAlias.product_id == p.id))
            )
            for p in products
        }

        for week_offset in range(weeks, 0, -1):
            week_start = monday - timedelta(weeks=week_offset)
            for product in products:
                for channel in channels:
                    if rng.random() < 0.25:  # 모든 채널에서 매주 팔리지는 않는다
                        continue

                    qty = max(
                        1,
                        int(
                            base_demand[product.product_code]
                            * rng.uniform(0.4, 1.6)
                            / len(channels)
                        ),
                    )
                    ship_date = week_start + timedelta(days=rng.randint(0, 6))
                    week = iso_week_of(ship_date)
                    unit_price = (product.purchase_price * Decimal("1.8")).quantize(
                        Decimal("1")
                    )
                    aliases = alias_by_product.get(product.id) or []
                    source_name = (
                        rng.choice(aliases).source_name if aliases else product.name
                    )

                    db.add(
                        SalesOrder(
                            brand_id=brand.id,
                            order_no=(
                                f"ORD-{ship_date:%Y%m%d}"
                                f"-{product.product_code}-{channel.id}"
                            ),
                            source_product_name=source_name,
                            source_channel_name=channel.name,
                            category="가전",
                            product_id=product.id,
                            channel_id=channel.id,
                            order_date=ship_date - timedelta(days=1),
                            ship_date=ship_date,
                            iso_year=week.year,
                            iso_week=week.week,
                            qty=qty,
                            unit_price=unit_price,
                            amount=unit_price * qty,
                        )
                    )
        db.commit()

    # ── 재고 스냅샷 (주 1회, 월요일) ─────────────────────────────────
    # 한 시점만 만들면 주차별 재고 변화를 알 수 없어 출고량이 계산되지 않고,
    # 예측 엔진의 평탄화 상수가 0이 된다. 실제 운영과 같이 매주 뜬다.
    if db.scalar(select(InventorySnapshot).limit(1)) is None:
        warehouses = list(db.scalars(select(Warehouse)))
        for product in products:
            for warehouse in warehouses:
                stock = rng.randint(3000, 9000)
                for week_offset in range(weeks, -1, -1):
                    snapshot_date = monday - timedelta(weeks=week_offset)
                    db.add(
                        InventorySnapshot(
                            snapshot_date=snapshot_date,
                            warehouse_id=warehouse.id,
                            product_id=product.id,
                            qty=stock,
                        )
                    )
                    # 매주 소진되다가 재고가 낮아지면 보충된다.
                    stock -= rng.randint(80, 260)
                    if stock < 800:
                        stock += rng.randint(2000, 4000)
                    stock = max(stock, 0)
        db.commit()

    # ── 입고 파이프라인 ──────────────────────────────────────────────
    if db.scalar(select(Inbound).limit(1)) is None:
        statuses = list(InboundStatus)
        for index, product in enumerate(products):
            for step, status in enumerate(statuses):
                eta = monday + timedelta(weeks=step * 3)
                qty = rng.randint(500, 3000)
                unit_price = product.purchase_price
                rate = Decimal("1385.50")
                db.add(
                    Inbound(
                        invoice_no=f"INV-2026-{index:02d}{step:02d}",
                        bl_no=f"BL{index:03d}{step:03d}",
                        purchase_code=f"PC-{product.product_code}-{step}",
                        production_code=f"PRD-{product.product_code}-{step}",
                        product_id=product.id,
                        arrival_warehouse_id=hub.id,
                        shipping_date=eta - timedelta(days=45),
                        eta=eta,
                        manufacture_date=eta - timedelta(days=60),
                        expiry_date=eta + timedelta(days=730),
                        carton_qty=qty,
                        unit_qty=qty,
                        unit_price=unit_price,
                        total_price=unit_price * qty,
                        exchange_rate=rate,
                        payment_amount_krw=(unit_price * qty * rate).quantize(Decimal("0.01")),
                        status=status,
                    )
                )
        db.commit()

    # ── 행사 ─────────────────────────────────────────────────────────
    # 판매 구간 안에 걸쳐야 리프트를 계산할 수 있다. 행사 시작 직전 14일이
    # 기준선이므로, 데이터 맨 앞에 붙이면 기준선이 비어 배수가 나오지 않는다.
    if db.scalar(select(Promotion).limit(1)) is None:
        product_by_source = {
            alias.source_name: alias.product_id
            for alias in db.scalars(select(ProductAlias))
        }
        channel_by_name = {channel.name: channel.id for channel in channels}
        list_price = Decimal("399000")

        def add_promotion(
            start: date, days: int, channel_name: str, source_product: str,
            slot: str, event: str,
        ) -> None:
            db.add(
                Promotion(
                    brand_id=brand.id,
                    start_date=start,
                    end_date=start + timedelta(days=days - 1),
                    source_product_name=source_product or None,
                    source_channel_name=channel_name,
                    product_id=product_by_source.get(source_product),
                    channel_id=channel_by_name.get(channel_name),
                    slot_name=slot,
                    event_name=event,
                    list_price=list_price,
                    price=(list_price * Decimal("0.8")).quantize(Decimal("1")),
                    discount_rate=Decimal("20.000"),
                    gift="사은품 필터 2종",
                    is_marketing=True,
                    is_confirmed=True,
                )
            )

        for channel_name, source_product, slot, event, days in PROMOTIONS:
            product_id = product_by_source.get(source_product)
            # 최근 판매 하나를 골라 그 날이 행사 둘째 날이 되게 붙인다.
            # 기준선(직전 14일)도 데이터 안에 들어오도록 마지막 주는 피한다.
            anchor_sale = db.scalar(
                select(SalesOrder.ship_date)
                .where(
                    SalesOrder.source_channel_name == channel_name,
                    SalesOrder.product_id == product_id,
                    SalesOrder.ship_date <= monday - timedelta(days=7),
                )
                .order_by(SalesOrder.ship_date.desc())
                .limit(1)
            )
            if anchor_sale is None:
                continue
            add_promotion(
                anchor_sale - timedelta(days=1), days, channel_name,
                source_product, slot, event,
            )

        channel_name, source_product, slot, event, days = UPCOMING_PROMOTION
        add_promotion(monday + timedelta(days=7), days, channel_name,
                      source_product, slot, event)
        db.commit()


def build_metrics(db: Session) -> int:
    """주차 집계를 만든다.

    집계 규칙은 services/derive.py 가 갖는다. 시드가 따로 구현하면 두 벌이
    되고 언젠가 어긋난다 — 화면에서 보는 값과 서버가 계산하는 값이 달라진다.
    """
    resolve_sales_mappings(db)
    result = rebuild_weekly_metrics(db)

    # 재고 흐름(기초·기말·출고)은 스냅샷이 있는 주차에만 채워진다.
    for week in {IsoWeek(m.iso_year, m.iso_week) for m in db.query(WeeklyMetric)}:
        apply_inventory_flow(db, week)

    return result.rows_written


def reset(db: Session) -> None:
    for model in (WeeklyMetric, SalesOrder, Inbound, InventorySnapshot, ProductAlias):
        db.query(model).delete()
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="개발용 시드 데이터 생성")
    parser.add_argument("--accounts-only", action="store_true", help="계정만 생성")
    parser.add_argument("--reset", action="store_true", help="실적 데이터를 지우고 다시 생성")
    parser.add_argument("--weeks", type=int, default=26, help="생성할 판매 실적 주 수")
    args = parser.parse_args()

    _guard_environment()

    with SessionLocal() as db:
        seed_accounts(db)
        print(f"계정 {len(DEV_ACCOUNTS)}개 준비 완료")

        if args.accounts_only:
            _print_credentials()
            return 0

        if args.reset:
            reset(db)
            print("기존 실적 데이터 삭제")

        brand = seed_master(db)
        print(
            f"마스터: 브랜드 1 · 창고 {len(WAREHOUSES)} · 채널 {len(CHANNELS)} · "
            f"품목 {len(PRODUCTS)} · 별칭 {len(ALIASES)}"
        )

        seed_activity(db, brand, weeks=args.weeks)
        orders = db.query(SalesOrder).count()
        inbounds = db.query(Inbound).count()
        snapshots = db.query(InventorySnapshot).count()
        promotions = db.query(Promotion).count()
        print(
            f"실적: 판매 {orders} · 입고 {inbounds} · 재고 {snapshots} · "
            f"행사 {promotions}"
        )

        metrics = build_metrics(db)
        print(f"주차 집계 {metrics}건 생성")

    _print_credentials()
    return 0


def _print_credentials() -> None:
    print("\n로그인 정보 (개발 전용)")
    for username, _, role in DEV_ACCOUNTS:
        print(f"  {username:9} / {DEV_PASSWORD}   [{role}]")


if __name__ == "__main__":
    raise SystemExit(main())

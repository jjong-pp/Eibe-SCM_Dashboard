import os
import random
from datetime import datetime, date, timedelta

from app.database import init_db, SessionLocal
from app.models import (
    ProductDB, WarehouseDB, LogisticsCostDB, WarehouseProductMOQ,
    OrderDB, ProductionDB, InboundDB,
    InventorySnapshot, MonthlyOrderPlan, SalesHistory, OutflowHistory
)

def clear_data(db):
    print("Clearing existing data...")
    db.query(OutflowHistory).delete()
    db.query(SalesHistory).delete()
    db.query(MonthlyOrderPlan).delete()
    db.query(InventorySnapshot).delete()
    db.query(InboundDB).delete()
    db.query(ProductionDB).delete()
    db.query(OrderDB).delete()
    db.query(WarehouseProductMOQ).delete()
    db.query(LogisticsCostDB).delete()
    db.query(WarehouseDB).delete()
    db.query(ProductDB).delete()
    db.commit()

def seed():
    init_db()
    db = SessionLocal()
    
    try:
        clear_data(db)
        
        print("Seeding Products...")
        products = [
            ProductDB(product_code="SN-001", product_name="슈누프로1단계 800g", pack_qty_per_tu=12, currency_unit="EUR", purchase_price=8.50),
            ProductDB(product_code="SN-002", product_name="슈누프로2단계 800g", pack_qty_per_tu=12, currency_unit="EUR", purchase_price=8.50),
            ProductDB(product_code="SN-003", product_name="슈누프로3단계 800g", pack_qty_per_tu=12, currency_unit="EUR", purchase_price=8.50),
            ProductDB(product_code="SN-004", product_name="슈누프로4단계 800g", pack_qty_per_tu=12, currency_unit="EUR", purchase_price=8.50),
        ]
        db.add_all(products)
        db.commit()
        
        print("Seeding Warehouses...")
        warehouses = [
            WarehouseDB(warehouse_name="용인 메인창고", warehouse_type="OFFLINE", allowed_expiry_days=180, moq=1200),
            WarehouseDB(warehouse_name="쿠팡 FFC", warehouse_type="ONLINE", allowed_expiry_days=90, moq=600),
            WarehouseDB(warehouse_name="오프라인 FFC", warehouse_type="OFFLINE", allowed_expiry_days=150, moq=600),
            WarehouseDB(warehouse_name="바이아웃 채널", warehouse_type="BUYOUT", allowed_expiry_days=60, moq=100),
        ]
        db.add_all(warehouses)
        db.commit()

        wh_main = warehouses[0].id
        wh_coupang = warehouses[1].id
        wh_offline = warehouses[2].id

        print("Seeding Logistics Costs...")
        costs = [
            LogisticsCostDB(departure_wh_id=wh_main, arrival_wh_id=wh_coupang, cost_per_tu=3500),
            LogisticsCostDB(departure_wh_id=wh_main, arrival_wh_id=wh_offline, cost_per_tu=4000),
        ]
        db.add_all(costs)
        db.commit()

        print("Seeding Orders, Productions, Inbounds (Pipeline)...")
        today = date.today()
        # Create pipeline data for the past 3 months
        for i in range(1, 4):
            month_str = (today - timedelta(days=30*i)).strftime("%Y-%m")
            
            for prod in products:
                # Order
                order_qty = random.randint(1000, 5000) * 12
                order = OrderDB(
                    order_month=month_str, product_code=prod.product_code, order_qty=order_qty,
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                db.add(order)
                db.commit()
                
                # Production
                production = ProductionDB(
                    purchase_code=f"PO-{month_str}-{prod.product_code}",
                    production_code=f"PRD-{month_str}-{prod.product_code}",
                    order_month=month_str,
                    production_qty=order_qty,
                    product_code=prod.product_code,
                    matched_order_id=order.id,
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                db.add(production)
                db.commit()

                db.commit()
                
                # Inbound (Invoice merged)
                carton_qty = int(order_qty / prod.pack_qty_per_tu)
                inbound = InboundDB(
                    invoice_no=f"INV-{month_str}-{prod.product_code}",
                    bl_no=f"BL-{month_str}-{prod.product_code}",
                    purchase_code=production.purchase_code,
                    production_code=production.production_code,
                    shipping_date=(today - timedelta(days=30*i - 5)).strftime("%Y-%m-%d"),
                    korea_arrival_date=(today - timedelta(days=30*i - 25)).strftime("%Y-%m-%d"),
                    eta=(today - timedelta(days=30*i - 15)).strftime("%Y-%m-%d"),
                    manufacture_date=(today - timedelta(days=30*i + 15)).strftime("%Y-%m-%d"),
                    expiry_date=(today + timedelta(days=365*2 - 30*i)).strftime("%Y-%m-%d"),
                    carton_qty=carton_qty,
                    can_qty=order_qty,
                    unit_price=prod.purchase_price,
                    total_price=carton_qty * prod.pack_qty_per_tu * prod.purchase_price,
                    payment_date=(today - timedelta(days=30*i - 20)).strftime("%Y-%m-%d"),
                    invoice_date=(today - timedelta(days=30*i)).strftime("%Y-%m-%d"),
                    exchange_rate=1400.0,
                    payment_amount_krw=int(carton_qty * prod.pack_qty_per_tu * prod.purchase_price * 1400.0),
                    arrival_wh_id=wh_main,

                    product_code=prod.product_code,
                    status="입고완료",
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                db.add(inbound)
                db.commit()

        print("Seeding Inventory Snapshots...")
        snap_date = today.strftime("%Y-%m-%d")
        for prod in products:
            for wh in warehouses:
                qty = random.randint(500, 3000) if wh.id == wh_main else random.randint(100, 1000)
                exp_date = (today + timedelta(days=random.choice([15, 45, 120, 200, 400]))).strftime("%Y-%m-%d")
                snap = InventorySnapshot(
                    snapshot_date=snap_date,
                    warehouse_id=wh.id,
                    warehouse_name=wh.warehouse_name,
                    product_name=prod.product_name,
                    product_code=prod.product_code,
                    expiry_date=exp_date,
                    qty_cans=qty
                )
                db.add(snap)
        db.commit()

        print("Seeding Sales & Outflow History...")
        for i in range(12):
            hist_date = (today - timedelta(days=7*i)).strftime("%Y-%m-%d")
            for prod in products:
                sales = SalesHistory(
                    product_id=prod.id,
                    warehouse_id=wh_main,
                    base_date=hist_date,
                    sales_qty=random.randint(500, 1500)
                )
                db.add(sales)
                
                outflow = OutflowHistory(
                    product_id=prod.id,
                    warehouse_id=wh_main,
                    base_date=hist_date,
                    beginning_inventory=0,
                    ending_inventory=0,
                    simple_outflow_qty=random.randint(400, 1200)
                )
                db.add(outflow)
        db.commit()

        print("Seeding Order Plans...")
        for i in range(1, 7):
            target = (today + timedelta(days=30*i)).strftime("%Y-%m")
            for prod in products:
                plan = MonthlyOrderPlan(
                    target_month=target,
                    product_id=prod.id,
                    system_suggested_qty=random.randint(1000, 5000),
                    user_modified_qty=random.randint(1000, 5000),
                    version=1,
                    updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                db.add(plan)
        db.commit()

        print("Seed data successfully injected!")
        
    except Exception as e:
        db.rollback()
        print(f"Error during seeding: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed()

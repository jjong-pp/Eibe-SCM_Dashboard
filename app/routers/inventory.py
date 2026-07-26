from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from typing import List, Optional
import os
import io
import math
import urllib.parse
from datetime import datetime, date, timedelta
import pandas as pd

from app.database import get_db, BASE_DIR, BACKUP_DIR
from app.models import *
from app.schemas import *
from app.core.auth import verify_password, get_password_hash, create_access_token, get_current_user, get_current_admin
from app.core.snapshot import create_snapshot

try:
    from app.core.excel_parser import generate_template, get_template_filename, parse_inventory_excel, generate_order_plan_export, TEMPLATE_LABELS
    _EXCEL_PARSER_AVAILABLE = True
except Exception:
    TEMPLATE_LABELS = {}
    _EXCEL_PARSER_AVAILABLE = False

try:
    from app.core.forecasting import *
    _FORECASTING_AVAILABLE = True
except Exception:
    _FORECASTING_AVAILABLE = False

router = APIRouter()
WEB_DIR = os.path.join(BASE_DIR, "web")

@router.get("/api/inventory-snapshot", response_model=List[InventorySnapshotResponse], tags=["재고 관리"])
def get_inventory_snapshots(
    warehouse_id: Optional[int] = Query(None),
    snapshot_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """현재고 스냅샷 조회"""
    query = db.query(InventorySnapshot)
    if warehouse_id:
        query = query.filter(InventorySnapshot.warehouse_id == warehouse_id)
    if snapshot_date:
        query = query.filter(InventorySnapshot.snapshot_date == snapshot_date)
    return query.order_by(InventorySnapshot.id.desc()).all()


@router.post("/api/inventory-snapshot", response_model=InventorySnapshotResponse, tags=["재고 관리"])
def create_inventory_snapshot(
    snap: InventorySnapshotCreate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재고 스냅샷 단건 등록"""
    dump = snap.model_dump()
    if not dump.get("updated_at"):
        dump["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db_snap = InventorySnapshot(**dump)
    db.add(db_snap)
    db.commit()
    db.refresh(db_snap)
    return db_snap


@router.delete("/api/inventory-snapshot/{snap_id}", response_model=MessageResponse, tags=["재고 관리"])
def delete_inventory_snapshot(
    snap_id: int,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재고 스냅샷 삭제"""
    obj = db.query(InventorySnapshot).filter(InventorySnapshot.id == snap_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="스냅샷 데이터를 찾을 수 없습니다")
    db.delete(obj)
    db.commit()
    return MessageResponse(message="스냅샷 삭제 완료")


@router.post("/api/inventory-snapshot/upload", response_model=MessageResponse, tags=["재고 관리"])
def upload_inventory_snapshot(
    file: UploadFile = File(...),
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재고 스냅샷 엑셀 업로드"""
    import pandas as pd

    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="xlsx 파일만 업로드 가능합니다")

    content = file.file.read()
    try:
        from app.core.excel_parser import parse_excel_file
        parsed_data = parse_excel_file(content, template_type="inventory_snapshot")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"엑셀 파일을 읽을 수 없습니다: {str(e)}")

    if not parsed_data:
        return MessageResponse(message="업로드할 데이터가 없습니다 (0건 등록).")

    created = 0
    try:
        for row in parsed_data:
            snap_date = str(row.get("snapshot_date", "")).strip()
            if not snap_date or snap_date == "None":
                continue

            # 창고 매핑 시도
            wh_id = None
            wh_name = str(row.get("warehouse_name", "")).strip() if row.get("warehouse_name") else None
            if wh_name and wh_name != "None":
                wh = db.query(WarehouseDB).filter(WarehouseDB.warehouse_name == wh_name).first()
                if wh:
                    wh_id = wh.id

            updated_at = str(row.get("updated_at", "")).strip() if row.get("updated_at") else None
            if not updated_at or updated_at == "None":
                updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
            qty = row.get("qty_cans")
            if qty is None or str(qty).lower() == "none":
                qty = 0

            new_snap = InventorySnapshot(
                snapshot_date=snap_date,
                warehouse_id=wh_id,
                warehouse_name=wh_name if wh_name != "None" else None,
                product_name=str(row.get("product_name", "")).strip() if row.get("product_name") and str(row.get("product_name")) != "None" else None,
                product_code=str(row.get("product_code", "")).strip() if row.get("product_code") and str(row.get("product_code")) != "None" else None,
                expiry_date=str(row.get("expiry_date", "")).strip() if row.get("expiry_date") and str(row.get("expiry_date")) != "None" else None,
                qty_cans=int(qty),
                updated_at=updated_at,
            )
            db.add(new_snap)
            created += 1

        db.commit()
    except ValueError as ve:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"입력값 형식이 올바르지 않습니다 (숫자 오류 등): {ve}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"엑셀 데이터 처리 중 오류 발생: {e}")
    return MessageResponse(message=f"스냅샷 업로드 완료: {created}건 등록")


@router.put("/api/inventory-snapshot/{snap_id}", response_model=InventorySnapshotResponse, tags=["재고 관리"])
def update_inventory_snapshot(
    snap_id: int,
    snap_update: InventorySnapshotCreate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재고 스냅샷 단건 수정 (권한 제한 등 가능)"""
    # Note: Authorization check could be added here if OPERATOR/ADMIN distinction is strict
    if current_user.role not in ["ADMIN", "OPERATOR"]:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    db_snap = db.query(InventorySnapshot).filter(InventorySnapshot.id == snap_id).first()
    if not db_snap:
        raise HTTPException(status_code=404, detail="스냅샷을 찾을 수 없습니다.")

    dump = snap_update.model_dump()
    if not dump.get("updated_at"):
        dump["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for key, value in dump.items():
        setattr(db_snap, key, value)
        
    db.commit()
    db.refresh(db_snap)
    return db_snap

@router.get("/api/inventory/summary", tags=["재고 관리"])
def get_inventory_summary(
    brand_category: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """전체 현재고 요약 (창고별, 품목별 집계 — InventorySnapshot 기반)"""
    
    # Helper to calculate actual unit price
    unit_price_cache = {}
    def get_unit_price(p_code, exp_date):
        if not p_code or not exp_date:
            return 0
        cache_key = (p_code, exp_date)
        if cache_key in unit_price_cache:
            return unit_price_cache[cache_key]
            
        inbound = db.query(InboundDB).filter(InboundDB.product_code == p_code, InboundDB.expiry_date == exp_date).first()
        price = 0
        if inbound and inbound.payment_amount_krw:
            qty = inbound.can_qty
            if not qty and inbound.carton_qty:
                prod = db.query(ProductDB).filter(ProductDB.product_code == p_code).first()
                if prod:
                    qty = inbound.carton_qty * prod.pack_qty_per_tu
            if qty and qty > 0:
                price = int(inbound.payment_amount_krw / qty)
        
        if not price:
            prod = db.query(ProductDB).filter(ProductDB.product_code == p_code).first()
            if prod:
                price = int(prod.purchase_price * 1350)
        
        unit_price_cache[cache_key] = price
        return price
    # 가장 최신 스냅샷 날짜 기준
    latest_date_row = db.query(func.max(InventorySnapshot.snapshot_date)).first()
    latest_date = latest_date_row[0] if latest_date_row and latest_date_row[0] else None
    if not latest_date:
        return []

    snapshots = (
        db.query(InventorySnapshot)
        .filter(InventorySnapshot.snapshot_date == latest_date)
        .all()
    )

    warehouses = {w.id: w for w in db.query(WarehouseDB).all()}
    products_dict = {p.product_code: p for p in db.query(ProductDB).all()}
    summary_by_wh: dict = {}

    for snap in snapshots:
        prod = products_dict.get(snap.product_code)
        if brand_category and (not prod or prod.brand_category != brand_category):
            continue
            
        wh_key = snap.warehouse_id or 0
        wh = warehouses.get(snap.warehouse_id) if snap.warehouse_id else None
        wh_name = wh.warehouse_name if wh else (snap.warehouse_name or "미지정")

        if wh_key not in summary_by_wh:
            summary_by_wh[wh_key] = {
                "warehouse_id": snap.warehouse_id,
                "warehouse_name": wh_name,
                "products": {},
                "total_qty": 0,
                "total_value_krw": 0,
            }

        prod_key = snap.product_code or snap.product_name or "UNKNOWN"
        if prod_key not in summary_by_wh[wh_key]["products"]:
            summary_by_wh[wh_key]["products"][prod_key] = {
                "product_code": snap.product_code,
                "product_name": snap.product_name,
                "total_qty": 0,
                "total_value_krw": 0,
                "batches": [],
            }

        remaining_days = None
        if snap.expiry_date and _FORECASTING_AVAILABLE:
            try:
                exp_date_only = snap.expiry_date.split(" ")[0]
                remaining_days = calc_remaining_expiry_days(exp_date_only)
            except Exception:
                pass

        summary_by_wh[wh_key]["products"][prod_key]["total_qty"] += snap.qty_cans
        
        unit_price = get_unit_price(snap.product_code, snap.expiry_date)
        batch_value = snap.qty_cans * unit_price
        summary_by_wh[wh_key]["products"][prod_key]["total_value_krw"] += batch_value
        summary_by_wh[wh_key]["total_value_krw"] += batch_value

        summary_by_wh[wh_key]["products"][prod_key]["batches"].append({
            "snapshot_id": snap.id,
            "qty_cans": snap.qty_cans,
            "expiry_date": snap.expiry_date,
            "remaining_days": remaining_days,
            "unit_price_krw": unit_price,
            "total_value_krw": batch_value,
            "updated_at": snap.updated_at,
        })
        summary_by_wh[wh_key]["total_qty"] += snap.qty_cans

    result = []
    for wh_data in summary_by_wh.values():
        wh_data["products"] = list(wh_data["products"].values())
        result.append(wh_data)
    return result


@router.get("/api/expiry/summary", tags=["유통기한 관리"])
def get_expiry_summary(
    brand_category: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """유통기한 임박 재고 요약 (InventorySnapshot + WarehouseDB.allowed_expiry_days)"""
    
    # Helper to calculate actual unit price
    unit_price_cache = {}
    def get_unit_price(p_code, exp_date):
        if not p_code or not exp_date:
            return 0
        cache_key = (p_code, exp_date)
        if cache_key in unit_price_cache:
            return unit_price_cache[cache_key]
            
        inbound = db.query(InboundDB).filter(InboundDB.product_code == p_code, InboundDB.expiry_date == exp_date).first()
        price = 0
        if inbound and inbound.payment_amount_krw is not None:
            qty = inbound.can_qty
            if not qty and inbound.carton_qty:
                prod = db.query(ProductDB).filter(ProductDB.product_code == p_code).first()
                if prod:
                    qty = inbound.carton_qty * prod.pack_qty_per_tu
            if qty and qty > 0:
                price = int(inbound.payment_amount_krw / qty)
        
        if not price:
            prod = db.query(ProductDB).filter(ProductDB.product_code == p_code).first()
            if prod:
                price = int(prod.purchase_price * 1350)
        
        unit_price_cache[cache_key] = price
        return price

    # Helper for weekly outflow
    outflow_cache = {}
    def get_weekly_outflow(wh_id, p_code):
        if not wh_id or not p_code:
            return 0.0
        cache_key = (wh_id, p_code)
        if cache_key in outflow_cache:
            return outflow_cache[cache_key]
            
        prod = db.query(ProductDB).filter(ProductDB.product_code == p_code).first()
        if not prod:
            outflow_cache[cache_key] = 0.0
            return 0.0
            
        outflows = db.query(OutflowHistory).filter(
            OutflowHistory.warehouse_id == wh_id,
            OutflowHistory.product_id == prod.id
        ).order_by(OutflowHistory.base_date.desc()).limit(12).all()
        
        if not outflows:
            outflow_cache[cache_key] = 0.0
            return 0.0
            
        avg = sum(o.simple_outflow_qty for o in outflows) / len(outflows)
        outflow_cache[cache_key] = avg
        return avg

    # 최신 스냅샷 기준
    latest_date_row = db.query(func.max(InventorySnapshot.snapshot_date)).first()
    latest_date = latest_date_row[0] if latest_date_row and latest_date_row[0] else None
    if not latest_date:
        return {"items": [], "total_risk_count": 0, "critical_count": 0, "warehouse_count": 0}

    snapshots = (
        db.query(InventorySnapshot)
        .filter(InventorySnapshot.snapshot_date == latest_date)
        .all()
    )
    warehouses = {w.id: w for w in db.query(WarehouseDB).all()}
    products_dict = {p.product_code: p for p in db.query(ProductDB).all()}

    items = []
    for snap in snapshots:
        prod = products_dict.get(snap.product_code)
        if brand_category and (not prod or prod.brand_category != brand_category):
            continue
            
        if not snap.expiry_date:
            continue
        try:
            exp_str = snap.expiry_date.split(" ")[0]
            expiry = date.fromisoformat(exp_str)
            remaining = (expiry - date.today()).days
        except Exception:
            continue

        if remaining > 180:
            continue

        wh = warehouses.get(snap.warehouse_id) if snap.warehouse_id else None
        threshold = wh.allowed_expiry_days if wh else 90
        
        sellable_days = remaining - threshold
        if sellable_days < 0:
            sellable_days = 0
            
        weekly_outflow = get_weekly_outflow(snap.warehouse_id, snap.product_code)
        daily_outflow = weekly_outflow / 7.0 if weekly_outflow > 0 else 0
        
        depletion_date = "-"
        if daily_outflow > 0:
            days_to_deplete = int(snap.qty_cans / daily_outflow)
            depletion_date = (date.today() + timedelta(days=days_to_deplete)).isoformat()
            
        expected_sales = daily_outflow * sellable_days
        additional_sales_required = snap.qty_cans - expected_sales
        if additional_sales_required < 0:
            additional_sales_required = 0
            
        unit_price = get_unit_price(snap.product_code, snap.expiry_date)
        disposal_value_krw = int(additional_sales_required) * unit_price

        items.append({
            "snapshot_id": snap.id,
            "warehouse_id": snap.warehouse_id,
            "warehouse_name": wh.warehouse_name if wh else (snap.warehouse_name or "미지정"),
            "product_code": snap.product_code,
            "product_name": snap.product_name,
            "qty_cans": snap.qty_cans,
            "expiry_date": snap.expiry_date,
            "remaining_days": remaining,
            "threshold_days": threshold,
            "is_locked": remaining <= threshold,
            "sellable_days": sellable_days,
            "depletion_date": depletion_date,
            "additional_sales_required": int(additional_sales_required),
            "disposal_value": disposal_value_krw,
            "unit_price_krw": unit_price
        })

    items.sort(key=lambda x: x["remaining_days"])
    wh_set = set(i["warehouse_id"] for i in items if i["warehouse_id"])
    return {
        "items": items,
        "total_risk_count": len(items),
        "critical_count": sum(1 for i in items if i["remaining_days"] <= 30),
        "warehouse_count": len(wh_set),
    }





@router.get("/api/order-plan/simulation", tags=["발주 계획"])
def get_order_plan_simulation(
    weight_factor: float = Query(default=1.0, ge=0.5, le=2.0),
    brand_category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """6개월(24주) 시뮬레이션 데이터 — 품목별"""
    if not _FORECASTING_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="포캐스팅 모듈을 사용할 수 없습니다 (app.core.forecasting 로드 실패)",
        )

    products = db.query(ProductDB).all()
    if brand_category:
        products = [p for p in products if p.brand_category == brand_category]
        
    # 최신 스냅샷 날짜 기준 필터링 (뻥튀기 버그 수정)
    latest_date_row = db.query(func.max(InventorySnapshot.snapshot_date)).first()
    latest_date = latest_date_row[0] if latest_date_row and latest_date_row[0] else None
    
    if latest_date:
        snapshots = db.query(InventorySnapshot).filter(InventorySnapshot.snapshot_date == latest_date).all()
    else:
        snapshots = []
        
    outflows = db.query(OutflowHistory).all()

    result = []
    
    # N+1 쿼리 최적화: SalesHistory 와 MonthlyOrderPlan 사전 로드
    product_ids = [p.id for p in products]
    all_sales = db.query(SalesHistory).filter(SalesHistory.product_id.in_(product_ids)).order_by(SalesHistory.base_date.desc()).all()
    all_plans = db.query(MonthlyOrderPlan).filter(MonthlyOrderPlan.product_id.in_(product_ids)).all()
    
    sales_by_product = {}
    for s in all_sales:
        sales_by_product.setdefault(s.product_id, []).append(s)
        
    plans_by_product = {}
    for p in all_plans:
        plans_by_product.setdefault(p.product_id, []).append(p)
    
    for product in products:
        # 현재 총 재고 (최신 스냅샷에서 품목코드 일치 건 합산)
        total_stock = sum(
            s.qty_cans
            for s in snapshots
            if s.product_code == product.product_code
        )

        # 출고 데이터 (날짜별 그룹핑 합산 버그 수정)
        product_outflows = [o for o in outflows if o.product_id == product.id]
        outflow_by_date = {}
        for o in product_outflows:
            outflow_by_date[o.base_date] = outflow_by_date.get(o.base_date, 0) + o.simple_outflow_qty
            
        sorted_outflow_dates = sorted(outflow_by_date.keys())
        outflow_values = [outflow_by_date[d] for d in sorted_outflow_dates]
        
        smoothing = calc_weekly_smoothing_constant(outflow_values) if outflow_values else 0

        # 판매 기반 감모 버퍼
        sales = sales_by_product.get(product.id, [])[:12]
        sales_data = [s.sales_qty for s in reversed(sales)] if sales else []
        loss_buffer = (
            calc_dynamic_loss_buffer(outflow_values, sales_data)
            if sales_data and outflow_values
            else 0
        )

        # 도착월 기준 발주 계획 데이터 통합
        today = date.today()
        plans = plans_by_product.get(product.id, [])
        expected_inbounds_dict = {}
        for p in plans:
            if p.arrival_month and p.user_modified_qty > 0:
                try:
                    arr_date = datetime.strptime(p.arrival_month, "%Y-%m").date()
                    delta_days = (arr_date - today).days
                    wk = int(delta_days / 7) + 1
                    if wk < 1: wk = 1
                    if wk <= 24:
                        expected_inbounds_dict[wk] = expected_inbounds_dict.get(wk, 0) + p.user_modified_qty
                except Exception:
                    pass

        # 시뮬레이션
        simulation = simulate_future_inventory(
            current_stock=total_stock,
            smoothing_constant=smoothing,
            loss_buffer=loss_buffer,
            pipeline_inbounds={},
            expected_inbounds=expected_inbounds_dict,
            weight_factor=weight_factor,
            weeks=24,
        )

        suggested_qty = 0
        if simulation and simulation[-1]["ending_stock"] < smoothing * 6:
            shortage = smoothing * 6 - simulation[-1]["ending_stock"]
            # MOQ 적용 (ProductDB.pack_qty_per_tu 활용)
            moq = product.pack_qty_per_tu if (product.pack_qty_per_tu and product.pack_qty_per_tu > 0) else 24
            suggested_qty = calc_order_suggestion(shortage, moq)

        today = date.today()
        target_month = (today + timedelta(weeks=24)).strftime("%Y-%m")
        saved_plan = (
            db.query(MonthlyOrderPlan)
            .filter(
                MonthlyOrderPlan.product_id == product.id,
                MonthlyOrderPlan.target_month == target_month,
            )
            .first()
        )

        result.append({
            "product_id": product.id,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "current_stock": total_stock,
            "weekly_avg_outflow": round(smoothing, 1),
            "loss_buffer": round(loss_buffer, 2),
            "simulation": simulation,
            "suggested_qty": suggested_qty,
            "target_month": target_month,
            "saved_qty": saved_plan.user_modified_qty if saved_plan else None,
            "version": saved_plan.version if saved_plan else 1,
        })

    return result


@router.post("/api/order-plan/save", response_model=MessageResponse, tags=["발주 계획"])
def save_order_plan(
    data: OrderPlanBulkSave,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """발주 계획 일괄 저장 (Upsert + 낙관적 잠금)"""
    saved = 0
    for item in data.plans:
        existing = (
            db.query(MonthlyOrderPlan)
            .filter(
                MonthlyOrderPlan.target_month == item.target_month,
                MonthlyOrderPlan.product_id == item.product_id,
            )
            .first()
        )
        if existing:
            if existing.version and item.version and existing.version != item.version:
                raise HTTPException(status_code=409, detail=f"데이터가 이미 다른 사용자에 의해 변경되었습니다. 새로고침 후 다시 시도해주세요. (품목: {item.product_id})")
            existing.user_modified_qty = item.user_modified_qty
            if item.arrival_month is not None:
                existing.arrival_month = item.arrival_month
            existing.version = (existing.version or 1) + 1
            existing.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            new_plan = MonthlyOrderPlan(
                target_month=item.target_month,
                arrival_month=item.arrival_month,
                product_id=item.product_id,
                system_suggested_qty=item.user_modified_qty,
                user_modified_qty=item.user_modified_qty,
                version=1,
                updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            db.add(new_plan)
        saved += 1
    db.commit()
    return MessageResponse(message=f"{saved}건 발주 계획 저장 완료")


@router.get("/api/order-plan", response_model=List[OrderPlanResponse], tags=["발주 계획"])
def get_order_plans(
    target_month: Optional[str] = Query(None, description="대상 연월 (YYYY-MM)"),
    db: Session = Depends(get_db),
):
    """월별 발주 계획 조회"""
    query = db.query(MonthlyOrderPlan)
    if target_month:
        query = query.filter(MonthlyOrderPlan.target_month == target_month)
    plans = query.all()
    result = []
    for p in plans:
        prod = db.query(ProductDB).filter(ProductDB.id == p.product_id).first()
        result.append(
            OrderPlanResponse(
                plan_id=p.plan_id,
                target_month=p.target_month,
                arrival_month=p.arrival_month,
                product_id=p.product_id,
                system_suggested_qty=p.system_suggested_qty,
                user_modified_qty=p.user_modified_qty,
                version=p.version or 1,
                updated_at=p.updated_at,
                product_code=prod.product_code if prod else None,
                product_name=prod.product_name if prod else None,
            )
        )
    return result


@router.delete("/api/order-plan/{plan_id}", response_model=MessageResponse, tags=["발주 계획"])
def delete_order_plan(
    plan_id: int,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """발주 계획 삭제"""
    obj = db.query(MonthlyOrderPlan).filter(MonthlyOrderPlan.plan_id == plan_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="발주 계획을 찾을 수 없습니다")
    db.delete(obj)
    db.commit()
    return MessageResponse(message="발주 계획 삭제 완료")


@router.get("/api/outflow", tags=["출고 관리"])
def get_outflow_history(
    product_id: Optional[int] = Query(None),
    warehouse_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """출고 이력 조회 (품목/창고 필터 지원)"""
    query = db.query(OutflowHistory)
    if product_id:
        query = query.filter(OutflowHistory.product_id == product_id)
    if warehouse_id:
        query = query.filter(OutflowHistory.warehouse_id == warehouse_id)
    return query.order_by(OutflowHistory.base_date.desc()).all()


@router.get("/api/sales", tags=["판매 실적"])
def get_sales(
    product_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """판매 실적 조회"""
    query = db.query(SalesHistory)
    if product_id:
        query = query.filter(SalesHistory.product_id == product_id)
    return query.order_by(SalesHistory.base_date.desc()).all()


@router.post("/api/sales", tags=["판매 실적"])
def create_sales(
    data: dict,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """판매 실적 등록"""
    db_sales = SalesHistory(
        warehouse_id=data.get("warehouse_id"),
        product_id=data.get("product_id"),
        base_date=data.get("base_date"),
        sales_qty=data.get("sales_qty", 0),
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(db_sales)
    db.commit()
    db.refresh(db_sales)
    return {"id": db_sales.sales_id, "message": "판매 실적 등록 완료"}


@router.get("/api/excel/template/{template_type}", tags=["파일 업로드"])
def get_excel_template(template_type: str):
    """엑셀 양식 다운로드"""
    if not _EXCEL_PARSER_AVAILABLE:
        # 폴백: 기본 빈 엑셀 생성
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = template_type

        # 템플릿 타입별 기본 헤더
        headers_map = {
            "product": ["product_code", "product_name", "pack_qty_per_tu", "currency_unit", "purchase_price"],
            "warehouse": ["warehouse_name", "warehouse_type", "allowed_expiry_days", "moq"],
            "inventory": ["snapshot_date", "warehouse_name", "product_code", "product_name", "expiry_date", "qty_cans"],
            "order": ["order_month", "product_code", "order_qty"],
            "production": ["purchase_code", "production_code", "order_month", "production_qty", "product_code"],
            "inbound": ["invoice_no", "bl_no", "mapping_value", "purchase_code", "production_code", "shipping_date", "korea_arrival_date", "eta", "manufacture_date", "expiry_date", "carton_qty", "can_qty", "unit_price", "total_price", "payment_date", "invoice_date", "exchange_rate", "payment_amount_krw", "product_code", "status"],
        }
        headers = headers_map.get(template_type, ["column1", "column2"])
        for col_idx, header in enumerate(headers, 1):
            ws.cell(row=1, column=col_idx, value=header)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        filename = urllib.parse.quote(f"{template_type}_양식.xlsx")
        return StreamingResponse(
            output,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # 기존 excel_parser 모듈 사용
    try:
        output = generate_template(template_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    filename = urllib.parse.quote(get_template_filename(template_type))
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return StreamingResponse(
        output,
        headers=headers,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/api/excel/template-types", tags=["데이터 수집"])
def get_template_types():
    """사용 가능한 엑셀 양식 종류 목록"""
    if _EXCEL_PARSER_AVAILABLE and TEMPLATE_LABELS:
        return [{"type": k, "label": v} for k, v in TEMPLATE_LABELS.items()]
    # 폴백
    return [
        {"type": "product", "label": "품목 마스터"},
        {"type": "warehouse", "label": "창고 마스터"},
        {"type": "inventory", "label": "현재고 스냅샷"},
        {"type": "order", "label": "발주"},
        {"type": "production", "label": "생산"},
        {"type": "inbound", "label": "입고"},
    ]


@router.post("/api/transfer/simulation", tags=["재고 관리"])
def simulate_inventory_transfer(
    file: UploadFile = File(...),
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """이관 시뮬레이터 엑셀 업로드 및 검증"""
    import pandas as pd
    
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="xlsx 파일만 업로드 가능합니다")
    
    content = file.file.read()
    try:
        df = pd.read_excel(io.BytesIO(content))
    except Exception:
        raise HTTPException(status_code=400, detail="엑셀 파일을 읽을 수 없습니다")
    
    # Get latest snapshot date
    latest_date_row = db.query(func.max(InventorySnapshot.snapshot_date)).first()
    latest_date = latest_date_row[0] if latest_date_row and latest_date_row[0] else None
    
    if not latest_date:
        raise HTTPException(status_code=400, detail="현재고 데이터가 없습니다")
        
    hub_wh = db.query(WarehouseDB).filter(WarehouseDB.warehouse_type == "HUB").first()
    hub_name = hub_wh.warehouse_name if hub_wh else "용인 메인창고"
    
    hub_inventory = db.query(InventorySnapshot).filter(
        InventorySnapshot.snapshot_date == latest_date,
        InventorySnapshot.warehouse_name == hub_name
    ).all()
    
    hub_stock_dict = {}
    for inv in hub_inventory:
        hub_stock_dict[inv.product_code] = hub_stock_dict.get(inv.product_code, 0) + inv.qty_cans
        
    products_dict = {p.product_code: p.product_name for p in db.query(ProductDB).all()}
    
    results = []
    
    # Example template headers: ['도착 창고명', '품목코드', '이관수량(캔)']
    # Support various column names for robustness
    wh_cols = [c for c in df.columns if "창고" in str(c) or "warehouse" in str(c).lower()]
    prod_cols = [c for c in df.columns if "품목코드" in str(c) or "product_code" in str(c).lower() or "코드" in str(c)]
    qty_cols = [c for c in df.columns if "수량" in str(c) or "qty" in str(c).lower()]
    
    if not (wh_cols and prod_cols and qty_cols):
        raise HTTPException(status_code=400, detail="엑셀 컬럼을 인식할 수 없습니다. '창고', '품목코드', '수량' 컬럼이 필요합니다.")
        
    wh_col, prod_col, qty_col = wh_cols[0], prod_cols[0], qty_cols[0]
    
    for _, row in df.iterrows():
        to_wh = str(row[wh_col]).strip()
        p_code = str(row[prod_col]).strip()
        qty = row[qty_col]
        
        if not p_code or pd.isna(row[prod_col]):
            continue
            
        try:
            qty = int(qty)
        except Exception:
            qty = 0
            
        if qty <= 0:
            continue
            
        before = hub_stock_dict.get(p_code, 0)
        after = before - qty
        hub_stock_dict[p_code] = after # Update for subsequent rows of the same product
        
        results.append({
            "product_code": p_code,
            "product_name": products_dict.get(p_code, "알 수 없음"),
            "to_warehouse": to_wh,
            "transfer_qty": qty,
            "hub_before": before,
            "hub_after": after
        })
        
    return results

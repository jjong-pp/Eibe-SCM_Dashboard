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
except Exception:
    TEMPLATE_LABELS = {}

try:
    from app.core.forecasting import *
except Exception:
    pass

router = APIRouter()
WEB_DIR = os.path.join(BASE_DIR, "web")

@router.get("/api/products", response_model=List[ProductResponse], tags=["기준 정보"])
def get_products(db: Session = Depends(get_db)):
    """전체 품목 목록 조회"""
    return db.query(ProductDB).all()


@router.post("/api/products", response_model=ProductResponse, tags=["기준 정보"])
def create_product(
    product: ProductCreate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """품목 등록 — product_code는 생성 후 수정 불가"""
    existing = db.query(ProductDB).filter(ProductDB.product_code == product.product_code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"품목코드 '{product.product_code}' 이미 존재")
    db_product = ProductDB(**product.model_dump())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


@router.put("/api/products/{product_id}", response_model=ProductResponse, tags=["기준 정보"])
def update_product(
    product_id: int,
    product: ProductUpdate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """품목 수정 — product_code는 변경 불가"""
    db_product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="품목을 찾을 수 없습니다")
    update_data = product.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_product, key, value)
    db.commit()
    db.refresh(db_product)
    return db_product


@router.delete("/api/products/{product_id}", response_model=MessageResponse, tags=["기준 정보"])
def delete_product(
    product_id: int,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """품목 삭제"""
    db_product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="품목을 찾을 수 없습니다")
    db.delete(db_product)
    db.commit()
    return MessageResponse(message="품목 삭제 완료", detail=f"'{db_product.product_name}' 삭제됨")


@router.get("/api/products/{product_id}", response_model=ProductResponse, tags=["기준 정보"])
def get_product(product_id: int, db: Session = Depends(get_db)):
    """특정 품목 상세 조회"""
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="품목을 찾을 수 없습니다")
    return product


@router.post("/api/products/upload", response_model=MessageResponse, tags=["기준 정보"])
def upload_products(
    file: UploadFile = File(...),
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """품목 엑셀 업로드 (일괄 등록/갱신)"""

    content = file.file.read()
    try:
        df = pd.read_excel(io.BytesIO(content))
    except Exception:
        raise HTTPException(status_code=400, detail="엑셀 파일을 읽을 수 없습니다")

    required_cols = {"product_code", "product_name"}
    if not required_cols.issubset(set(df.columns)):
        raise HTTPException(status_code=400, detail=f"필수 컬럼 누락: {required_cols - set(df.columns)}")

    created, updated = 0, 0
    try:
        for _, row in df.iterrows():
            code = str(row["product_code"]).strip()
            if not code or pd.isna(row["product_code"]):
                continue
            existing = db.query(ProductDB).filter(ProductDB.product_code == code).first()
            qty_col = (
                "pack_qty_per_tu"
                if "pack_qty_per_tu" in df.columns
                else "pcs_per_carton"
                if "pcs_per_carton" in df.columns
                else None
            )
            if existing:
                if "product_name" in df.columns and pd.notna(row["product_name"]):
                    existing.product_name = str(row["product_name"]).strip()
                if "brand_category" in df.columns and pd.notna(row.get("brand_category")):
                    existing.brand_category = str(row["brand_category"]).strip()
                if qty_col and pd.notna(row.get(qty_col)):
                    existing.pack_qty_per_tu = int(row[qty_col])
                if "currency_unit" in df.columns and pd.notna(row.get("currency_unit")):
                    existing.currency_unit = str(row["currency_unit"]).strip()
                if "purchase_price" in df.columns and pd.notna(row.get("purchase_price")):
                    existing.purchase_price = float(row["purchase_price"])
                updated += 1
            else:
                new_product = ProductDB(
                    product_code=code,
                    product_name=str(row.get("product_name", "")).strip() if pd.notna(row.get("product_name")) else "",
                    brand_category=(
                        str(row["brand_category"]).strip()
                        if "brand_category" in df.columns and pd.notna(row.get("brand_category"))
                        else "FOOD"
                    ),
                    pack_qty_per_tu=(
                        int(row.get(qty_col, 24)) if qty_col and pd.notna(row.get(qty_col)) else 24
                    ),
                    currency_unit=(
                        str(row["currency_unit"]).strip()
                        if "currency_unit" in df.columns and pd.notna(row.get("currency_unit"))
                        else "USD"
                    ),
                    purchase_price=(
                        float(row["purchase_price"])
                        if "purchase_price" in df.columns and pd.notna(row.get("purchase_price"))
                        else 0
                    ),
                )
                db.add(new_product)
                created += 1
        db.commit()
    except ValueError as ve:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"입력값 형식이 올바르지 않습니다 (숫자 오류 등): {ve}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"엑셀 데이터 처리 중 오류 발생: {e}")

    return MessageResponse(message=f"업로드 완료: {created}건 신규, {updated}건 갱신")


@router.get("/api/warehouses", response_model=List[WarehouseResponse], tags=["기준 정보"])
def get_warehouses(db: Session = Depends(get_db)):
    """전체 창고 목록 조회"""
    return db.query(WarehouseDB).all()


@router.post("/api/warehouses", response_model=WarehouseResponse, tags=["기준 정보"])
def create_warehouse(
    wh: WarehouseCreate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """창고 등록 — id 자동생성, warehouse_name 수정 불가"""
    existing = db.query(WarehouseDB).filter(WarehouseDB.warehouse_name == wh.warehouse_name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"창고명 '{wh.warehouse_name}' 이미 존재")
    db_wh = WarehouseDB(**wh.model_dump())
    db.add(db_wh)
    db.commit()
    db.refresh(db_wh)
    return db_wh


@router.put("/api/warehouses/{wh_id}", response_model=WarehouseResponse, tags=["기준 정보"])
def update_warehouse(
    wh_id: int,
    wh: WarehouseUpdate,
    current_user: UserAccount = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """창고 수정 — warehouse_name은 변경 불가 (ADMIN 전용)"""
    db_wh = db.query(WarehouseDB).filter(WarehouseDB.id == wh_id).first()
    if not db_wh:
        raise HTTPException(status_code=404, detail="창고를 찾을 수 없습니다")
    update_data = wh.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_wh, key, value)
    db.commit()
    db.refresh(db_wh)
    return db_wh


@router.delete("/api/warehouses/{wh_id}", response_model=MessageResponse, tags=["기준 정보"])
def delete_warehouse(
    wh_id: int,
    current_user: UserAccount = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """창고 삭제 (ADMIN 전용)"""
    db_wh = db.query(WarehouseDB).filter(WarehouseDB.id == wh_id).first()
    if not db_wh:
        raise HTTPException(status_code=404, detail="창고를 찾을 수 없습니다")
    db.delete(db_wh)
    db.commit()
    return MessageResponse(message="삭제 완료", detail=f"창고 '{db_wh.warehouse_name}' 삭제됨")


@router.get("/api/logistics-cost", response_model=List[LogisticsCostResponse], tags=["기준 정보"])
def get_logistics_costs(db: Session = Depends(get_db)):
    """물류비 단가 목록 조회"""
    costs = db.query(LogisticsCostDB).all()
    result = []
    for c in costs:
        dep = db.query(WarehouseDB).filter(WarehouseDB.id == c.departure_wh_id).first()
        arr = db.query(WarehouseDB).filter(WarehouseDB.id == c.arrival_wh_id).first()
        result.append(
            LogisticsCostResponse(
                departure_wh_id=c.departure_wh_id,
                arrival_wh_id=c.arrival_wh_id,
                cost_per_tu=c.cost_per_tu,
                departure_name=dep.warehouse_name if dep else None,
                arrival_name=arr.warehouse_name if arr else None,
            )
        )
    return result


@router.post("/api/logistics-cost", response_model=MessageResponse, tags=["기준 정보"])
def upsert_logistics_cost(
    cost: LogisticsCostCreate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """물류비 단가 등록/수정 (Upsert)"""
    existing = (
        db.query(LogisticsCostDB)
        .filter(
            LogisticsCostDB.departure_wh_id == cost.departure_wh_id,
            LogisticsCostDB.arrival_wh_id == cost.arrival_wh_id,
        )
        .first()
    )
    if existing:
        existing.cost_per_tu = cost.cost_per_tu
        db.commit()
        return MessageResponse(message="물류비 단가가 수정되었습니다")
    else:
        new_cost = LogisticsCostDB(**cost.model_dump())
        db.add(new_cost)
        db.commit()
        return MessageResponse(message="물류비 단가가 등록되었습니다")


@router.delete("/api/logistics-cost", response_model=MessageResponse, tags=["기준 정보"])
def delete_logistics_cost(
    departure_wh_id: int = Query(...),
    arrival_wh_id: int = Query(...),
    current_user: UserAccount = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """물류비 단가 삭제"""
    existing = (
        db.query(LogisticsCostDB)
        .filter(
            LogisticsCostDB.departure_wh_id == departure_wh_id,
            LogisticsCostDB.arrival_wh_id == arrival_wh_id,
        )
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="물류비 데이터를 찾을 수 없습니다")
    db.delete(existing)
    db.commit()
    return MessageResponse(message="물류비 삭제 완료")


@router.get("/api/warehouse-moq", response_model=List[WarehouseProductMOQResponse], tags=["기준 정보"])
def get_warehouse_moqs(
    warehouse_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """창고-품목별 이관 MOQ 조회"""
    query = db.query(WarehouseProductMOQ)
    if warehouse_id:
        query = query.filter(WarehouseProductMOQ.warehouse_id == warehouse_id)
    moqs = query.all()
    result = []
    for m in moqs:
        wh = db.query(WarehouseDB).filter(WarehouseDB.id == m.warehouse_id).first()
        prod = db.query(ProductDB).filter(ProductDB.id == m.product_id).first()
        result.append(
            WarehouseProductMOQResponse(
                id=m.id,
                warehouse_id=m.warehouse_id,
                product_id=m.product_id,
                transfer_moq=m.transfer_moq,
                warehouse_name=wh.warehouse_name if wh else None,
                product_name=prod.product_name if prod else None,
            )
        )
    return result


@router.post("/api/warehouse-moq", response_model=WarehouseProductMOQResponse, tags=["기준 정보"])
def upsert_warehouse_moq(
    moq: WarehouseProductMOQCreate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """창고-품목별 이관 MOQ 등록/수정 (Upsert)"""
    existing = (
        db.query(WarehouseProductMOQ)
        .filter(
            WarehouseProductMOQ.warehouse_id == moq.warehouse_id,
            WarehouseProductMOQ.product_id == moq.product_id,
        )
        .first()
    )
    if existing:
        existing.transfer_moq = moq.transfer_moq
        db.commit()
        db.refresh(existing)
        obj = existing
    else:
        db_moq = WarehouseProductMOQ(**moq.model_dump())
        db.add(db_moq)
        db.commit()
        db.refresh(db_moq)
        obj = db_moq

    wh = db.query(WarehouseDB).filter(WarehouseDB.id == obj.warehouse_id).first()
    prod = db.query(ProductDB).filter(ProductDB.id == obj.product_id).first()
    return WarehouseProductMOQResponse(
        id=obj.id,
        warehouse_id=obj.warehouse_id,
        product_id=obj.product_id,
        transfer_moq=obj.transfer_moq,
        warehouse_name=wh.warehouse_name if wh else None,
        product_name=prod.product_name if prod else None,
    )


@router.delete("/api/warehouse-moq", response_model=MessageResponse, tags=["기준 정보"])
def delete_warehouse_moq(
    warehouse_id: int = Query(...),
    product_id: int = Query(...),
    current_user: UserAccount = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """창고-품목별 이관 MOQ 삭제"""
    existing = (
        db.query(WarehouseProductMOQ)
        .filter(
            WarehouseProductMOQ.warehouse_id == warehouse_id,
            WarehouseProductMOQ.product_id == product_id,
        )
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="MOQ 데이터를 찾을 수 없습니다")
    db.delete(existing)
    db.commit()
    return MessageResponse(message="MOQ 삭제 완료")



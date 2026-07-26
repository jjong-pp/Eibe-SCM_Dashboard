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

@router.get("/api/orders", response_model=List[OrderResponse], tags=["입고 파이프라인"])
def get_orders(
    product_code: Optional[str] = Query(None),
    order_month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """발주 목록 조회"""
    query = db.query(OrderDB)
    if product_code:
        query = query.filter(OrderDB.product_code == product_code)
    if order_month:
        query = query.filter(OrderDB.order_month == order_month)
    orders = query.order_by(OrderDB.id.desc()).all()
    
    # N+1 쿼리 방지: In-memory Dict 활용
    product_codes = list(set([o.product_code for o in orders if o.product_code]))
    products = db.query(ProductDB).filter(ProductDB.product_code.in_(product_codes)).all()
    prod_dict = {p.product_code: p.product_name for p in products}
    
    result = []
    for o in orders:
        result.append(
            OrderResponse(
                id=o.id,
                order_month=o.order_month,
                product_code=o.product_code,
                order_qty=o.order_qty,
                created_at=o.created_at,
                product_name=prod_dict.get(o.product_code),
            )
        )
    return result


@router.post("/api/orders", response_model=OrderResponse, tags=["입고 파이프라인"])
def create_order(
    order: OrderCreate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """발주 등록"""
    # 품목코드 유효성 검증
    prod = db.query(ProductDB).filter(ProductDB.product_code == order.product_code).first()
    if not prod:
        raise HTTPException(status_code=400, detail=f"품목코드 '{order.product_code}'가 존재하지 않습니다")
    db_order = OrderDB(
        **order.model_dump(),
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return OrderResponse(
        id=db_order.id,
        order_month=db_order.order_month,
        product_code=db_order.product_code,
        order_qty=db_order.order_qty,
        created_at=db_order.created_at,
        product_name=prod.product_name,
    )


@router.delete("/api/orders/{order_id}", response_model=MessageResponse, tags=["입고 파이프라인"])
def delete_order(
    order_id: int,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """발주 삭제"""
    obj = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="발주 데이터를 찾을 수 없습니다")
    db.delete(obj)
    db.commit()
    return MessageResponse(message="발주 삭제 완료")


@router.get("/api/productions", response_model=List[ProductionResponse], tags=["입고 파이프라인"])
def get_productions(
    product_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """생산 목록 조회"""
    query = db.query(ProductionDB)
    if product_code:
        query = query.filter(ProductionDB.product_code == product_code)
    productions = query.order_by(ProductionDB.id.desc()).all()
    
    product_codes = list(set([p.product_code for p in productions if p.product_code]))
    products = db.query(ProductDB).filter(ProductDB.product_code.in_(product_codes)).all()
    prod_dict = {pr.product_code: pr.product_name for pr in products}
    
    result = []
    for p in productions:
        result.append(
            ProductionResponse(
                id=p.id,
                purchase_code=p.purchase_code,
                production_code=p.production_code,
                order_month=p.order_month,
                production_qty=p.production_qty,
                product_code=p.product_code,
                matched_order_id=p.matched_order_id,
                created_at=p.created_at,
                product_name=prod_dict.get(p.product_code),
            )
        )
    return result


@router.post("/api/productions", response_model=ProductionResponse, tags=["입고 파이프라인"])
def create_production(
    prod_data: ProductionCreate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """생산 등록"""
    product = db.query(ProductDB).filter(ProductDB.product_code == prod_data.product_code).first()
    if not product:
        raise HTTPException(status_code=400, detail=f"품목코드 '{prod_data.product_code}'가 존재하지 않습니다")
    db_prod = ProductionDB(
        **prod_data.model_dump(),
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(db_prod)
    db.commit()
    db.refresh(db_prod)
    return ProductionResponse(
        id=db_prod.id,
        purchase_code=db_prod.purchase_code,
        production_code=db_prod.production_code,
        order_month=db_prod.order_month,
        production_qty=db_prod.production_qty,
        product_code=db_prod.product_code,
        matched_order_id=db_prod.matched_order_id,
        created_at=db_prod.created_at,
        product_name=product.product_name,
    )


@router.delete("/api/productions/{prod_id}", response_model=MessageResponse, tags=["입고 파이프라인"])
def delete_production(
    prod_id: int,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """생산 삭제"""
    obj = db.query(ProductionDB).filter(ProductionDB.id == prod_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="생산 데이터를 찾을 수 없습니다")
    db.delete(obj)
    db.commit()
    return MessageResponse(message="생산 삭제 완료")


@router.get("/api/inbound", response_model=List[InboundResponse], tags=["입고 파이프라인"])
def get_inbounds(
    status_filter: Optional[str] = Query(None, alias="status"),
    brand_category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """입고 리스트 조회 (상태 필터 지원)"""
    query = db.query(InboundDB)
    if status_filter:
        query = query.filter(InboundDB.status == status_filter)
        
    inbounds = query.order_by(InboundDB.id.desc()).all()
    if brand_category:
        # Filter in Python level to match ProductDB brand_category
        products_dict = {p.product_code: p for p in db.query(ProductDB).all()}
        filtered = []
        for inv in inbounds:
            prod = products_dict.get(inv.product_code)
            if prod and prod.brand_category == brand_category:
                filtered.append(inv)
        return filtered
        
    return inbounds


@router.post("/api/inbound", response_model=InboundResponse, tags=["입고 파이프라인"])
def create_inbound(
    inbound: InboundCreate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """입고 등록"""
    db_inbound = InboundDB(**inbound.model_dump())
    db.add(db_inbound)
    db.commit()
    db.refresh(db_inbound)
    return db_inbound


@router.put("/api/inbound/{inbound_id}", response_model=InboundResponse, tags=["입고 파이프라인"])
def update_inbound(
    inbound_id: int,
    inbound_data: InboundUpdate,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """입고 수정 (상태 업데이트 포함)"""
    db_inbound = db.query(InboundDB).filter(InboundDB.id == inbound_id).first()
    if not db_inbound:
        raise HTTPException(status_code=404, detail="입고 데이터를 찾을 수 없습니다")
    
    data = inbound_data.model_dump(exclude_unset=True)
    
    # 상태 변경 유효성 검증
    if "status" in data and data["status"] not in VALID_INBOUND_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 상태입니다. 허용: {VALID_INBOUND_STATUSES}",
        )
    
    for k, v in data.items():
        setattr(db_inbound, k, v)
        
    db.commit()
    db.refresh(db_inbound)
    return db_inbound


@router.delete("/api/inbound/{inbound_id}", response_model=MessageResponse, tags=["입고 파이프라인"])
def delete_inbound(
    inbound_id: int,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """입고 삭제"""
    obj = db.query(InboundDB).filter(InboundDB.id == inbound_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="입고 데이터를 찾을 수 없습니다")
    db.delete(obj)
    db.commit()
    return MessageResponse(message="입고 삭제 완료")


# @router.post("/api/matching/link", ...) 및 @router.get("/api/matching/status", ...) 는
# 브랜드 중심 아키텍처 개편 및 입고 파이프라인 단순화에 따라 비활성화 됨.



from app.core.excel_parser import parse_excel_file

@router.post("/api/orders/upload", response_model=MessageResponse, tags=["입고 파이프라인"])
def upload_orders(
    file: UploadFile = File(...),
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        contents = file.file.read()
        records = parse_excel_file(contents, "order")
        created = 0
        for r in records:
            obj = OrderDB(**r)
            db.add(obj)
            created += 1
        db.commit()
        return MessageResponse(message=f"발주 업로드 완료: {created}건 등록")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"엑셀 처리 중 오류: {str(e)}")

@router.post("/api/productions/upload", response_model=MessageResponse, tags=["입고 파이프라인"])
def upload_productions(
    file: UploadFile = File(...),
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        contents = file.file.read()
        records = parse_excel_file(contents, "production")
        created = 0
        for r in records:
            obj = ProductionDB(**r)
            db.add(obj)
            created += 1
        db.commit()
        return MessageResponse(message=f"생산 업로드 완료: {created}건 등록")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"엑셀 처리 중 오류: {str(e)}")

@router.post("/api/inbound/upload", response_model=MessageResponse, tags=["입고 파이프라인"])
def upload_inbound(
    file: UploadFile = File(...),
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        contents = file.file.read()
        records = parse_excel_file(contents, "inbound")
        created = 0
        for r in records:
            obj = InboundDB(**r)
            db.add(obj)
            created += 1
        db.commit()
        return MessageResponse(message=f"입고 업로드 완료: {created}건 등록")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"엑셀 처리 중 오류: {str(e)}")

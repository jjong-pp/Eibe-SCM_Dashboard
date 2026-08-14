"""
엑셀 양식 · 업로드 API.

프론트에서 SheetJS 를 걷어냈으므로 파싱은 서버가 전담한다. 브라우저에서
파싱하면 규칙이 두 벌이 되고, 잘못된 파일을 걸러내는 기준도 갈린다.

업로드는 **행 단위로 실패한다.** 한 줄이 잘못됐다고 전체를 되돌리지 않고,
몇 번째 줄의 어느 칸이 왜 틀렸는지 목록으로 돌려준다.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_operator, require_viewer
from app.database import get_db
from app.models.auth import Role, User
from app.models.master import Brand
from app.schemas.common import ORMModel
from app.services import excel

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/excel",
    tags=["엑셀"],
    dependencies=[Depends(require_viewer)],
)

_XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

#: 기준 정보 업로드는 관리자, 업무 데이터는 운영자.
_MASTER_KINDS = {excel.Kind.PRODUCT, excel.Kind.WAREHOUSE, excel.Kind.CHANNEL}

#: 파일 하나가 차지할 수 있는 최대 크기. 무제한이면 메모리로 그대로 들어온다.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class TemplateInfo(ORMModel):
    kind: str
    sheet_name: str
    filename: str
    columns: list[str]
    required_columns: list[str]


class RowErrorResponse(BaseModel):
    row_no: int
    column: str
    message: str


class UploadResponse(BaseModel):
    kind: str
    created: int
    updated: int
    #: 읽히지 않은 행. 위치와 사유가 함께 온다.
    errors: list[RowErrorResponse]
    #: 저장은 됐지만 매핑되지 않은 원본 값 — 집계에서 빠진다
    unresolved: list[str]
    blank_rows: int
    #: 판매 업로드에서만 채워진다
    weeks_rebuilt: int | None = None
    message: str


@router.get("/templates", response_model=list[TemplateInfo])
def list_templates() -> list[TemplateInfo]:
    """받을 수 있는 양식 목록."""
    return [
        TemplateInfo(
            kind=template.kind.value,
            sheet_name=template.sheet_name,
            filename=template.filename,
            columns=template.headers,
            required_columns=[
                column.header for column in template.columns if column.required
            ],
        )
        for template in excel.TEMPLATES.values()
    ]


def _attachment(filename: str) -> str:
    """한글 파일명은 RFC 5987 로 인코딩한다. 그대로 넣으면 헤더가 깨진다."""
    return f"attachment; filename*=UTF-8''{quote(filename)}"


@router.get("/templates/{kind}")
def download_template(kind: str) -> StreamingResponse:
    """양식 다운로드. `kind=all` 이면 전 시트를 한 파일로 받는다."""
    target = None if kind == "all" else kind
    try:
        buffer = excel.generate_template(target)
        filename = excel.template_filename(target)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return StreamingResponse(
        buffer,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": _attachment(filename)},
    )


@router.post("/uploads/{kind}", response_model=UploadResponse)
def upload(
    kind: str,
    file: UploadFile = File(...),
    brand_id: int | None = Query(
        default=None, description="판매·행사 업로드에 필요"
    ),
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """엑셀 업로드.

    판매 업로드는 끝나면 해당 주차만 다시 집계한다. 전체 재계산은 응답을
    느리게 만들고, 손대지 않은 과거 주차까지 건드릴 이유가 없다.
    """
    try:
        template = excel.get_template(kind)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    # 종류가 경로 변수라 라우터 의존성으로는 권한을 나눌 수 없다. 기본은
    # 운영자이고, 기준 정보만 여기서 관리자를 추가로 요구한다.
    if template.kind in _MASTER_KINDS and not Role(current_user.role).can_act_as(
        Role.ADMIN
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "기준 정보 업로드에는 관리자 권한이 필요합니다.",
        )

    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"파일이 너무 큽니다. {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 이하로 올려주세요.",
        )
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "빈 파일입니다.")

    try:
        parsed = excel.parse(template.kind, content)
    except ValueError as exc:
        # 열이 없거나 파일 자체가 깨진 경우 — 행 단위로 넘어갈 수 없다.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    result = _dispatch(db, template.kind, parsed, brand_id)

    return UploadResponse(
        kind=template.kind.value,
        created=result.created,
        updated=result.updated,
        errors=[
            RowErrorResponse(
                row_no=error.row_no, column=error.column, message=error.message
            )
            for error in result.errors
        ],
        unresolved=result.unresolved,
        blank_rows=parsed.blank_rows,
        weeks_rebuilt=result.rebuild.weeks_covered if result.rebuild else None,
        message=str(result),
    )


def _dispatch(
    db: Session, kind: excel.Kind, parsed: excel.ParseResult, brand_id: int | None
) -> excel.ImportResult:
    if kind in _MASTER_KINDS:
        return excel.import_master(db, parsed)
    if kind is excel.Kind.INVENTORY_SNAPSHOT:
        return excel.import_inventory_snapshots(db, parsed)
    if kind is excel.Kind.INBOUND:
        return excel.import_inbounds(db, parsed)

    # 판매·행사는 브랜드에 속한다.
    if brand_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "brand_id 가 필요합니다. 어느 브랜드의 데이터인지 지정하세요.",
        )
    if db.get(Brand, brand_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "브랜드 정보를 찾을 수 없습니다.")

    if kind is excel.Kind.SALES_ORDER:
        return excel.import_sales_orders(db, parsed, brand_id=brand_id)
    return excel.import_promotions(db, parsed, brand_id=brand_id)

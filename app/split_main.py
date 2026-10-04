import os
import re

base_dir = r"C:\Users\parkj\.gemini\antigravity\worktrees\SCM-dashboad\refactor-add-error-handling\app"
main_path = os.path.join(base_dir, "main.py")
routers_dir = os.path.join(base_dir, "routers")
os.makedirs(routers_dir, exist_ok=True)

with open(os.path.join(routers_dir, "__init__.py"), "w", encoding="utf-8") as f:
    pass

with open(main_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

blocks = []
current_block = []
current_type = "header"

for line in lines:
    if line.startswith("@app.get(") or line.startswith("@app.post(") or line.startswith("@app.put(") or line.startswith("@app.delete("):
        # Save previous block
        blocks.append((current_type, current_block))
        current_block = [line]
        # Determine new type
        if "include_in_schema=False" in line:
            current_type = "views"
        elif "tags=[\"인증\"]" in line:
            current_type = "auth"
        elif "tags=[\"시스템\"]" in line or "tags=[\"시스템 관리\"]" in line:
            current_type = "system"
        elif "tags=[\"사용자 관리\"]" in line:
            current_type = "users"
        elif "tags=[\"기준 정보\"]" in line:
            current_type = "master"
        elif "tags=[\"입고 파이프라인\"]" in line:
            current_type = "pipeline"
        elif "tags=[\"재고 관리\"]" in line or "tags=[\"유통기한 관리\"]" in line or "tags=[\"이관 계획\"]" in line or "tags=[\"발주 계획\"]" in line:
            current_type = "inventory"
        elif "tags=[\"매칭\"]" in line or "tags=[\"템플릿\"]" in line or "tags=[\"다운로드\"]" in line:
            current_type = "pipeline"
        else:
            # Fallback to last known type if possible, or inventory
            current_type = "inventory"
    elif line.startswith("# ════════════════"):
        if current_type != "header":
            blocks.append((current_type, current_block))
            current_block = [line]
            current_type = "divider"
        else:
            current_block.append(line)
    else:
        current_block.append(line)

blocks.append((current_type, current_block))

# Common imports for routers
router_imports = """from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
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
"""

routers_content = {
    "views": router_imports.replace("APIRouter()", "APIRouter(include_in_schema=False)"),
    "auth": router_imports + "\n",
    "system": router_imports + "\n",
    "users": router_imports + "\n",
    "master": router_imports + "\n",
    "pipeline": router_imports + "\n",
    "inventory": router_imports + "\n"
}

header_content = []

for b_type, b_content in blocks:
    content_str = "".join(b_content).replace("@app.", "@router.")
    if b_type == "header":
        header_content.append(content_str)
    elif b_type in routers_content:
        routers_content[b_type] += content_str
    elif b_type == "divider":
        pass
    else:
        print(f"Unknown block type: {b_type}")

for router_name, content in routers_content.items():
    with open(os.path.join(routers_dir, f"{router_name}.py"), "w", encoding="utf-8") as f:
        f.write(content)

print("Split completed successfully!")

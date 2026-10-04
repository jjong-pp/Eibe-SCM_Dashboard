

let brandList = [];
let currentBrand = SheetSchema.DEFAULT_BRAND_SLUG;
let currentSheetId = "promo";
let workingRows = [];
let activeCell = null;
let sheetDirty = false;
let persistBusy = false;

const SHEET_PAGE_SIZE = 50;

const SHEET_TRAIL_EMPTY = 10;
let sheetTotalRows = 0;
let sheetServerLoadedCount = 0;

let sheetWindowStart = 0;
let sheetFullyLoaded = true;
let sheetPageLoading = false;

let sheetLoadError = false;

let pendingScrollToEnd = false;

function isRawSheet() {
  return currentSheetId === "raw";
}

function sheetDef() {
  return SheetSchema.getSheetDef(currentSheetId);
}

function flashSaveHint(msg) {
  const hint = document.getElementById("saveHint");
  if (!hint) return;
  hint.textContent = msg || "저장됨 · " + new Date().toLocaleTimeString("ko-KR");
  hint.classList.add("flash");
  setTimeout(() => {
    hint.classList.remove("flash");
    if (sheetDirty) updateDirtyUi();
  }, 900);
}

function updateDirtyUi() {
  const hint = document.getElementById("saveHint");
  const btn = document.getElementById("applySheetBtn");
  if (hint) {
    hint.classList.toggle("is-dirty", sheetDirty);
    if (sheetLoadError) {
      hint.textContent =
        "시트 로드 오류 · 엑셀 「전체 교체」로 마이그레이션 가능";
    } else if (sheetDirty) {
      hint.textContent = "미반영 변경 있음 · 「입력 반영」 필요";
    } else if (!sheetFullyLoaded && sheetTotalRows > 0) {
      if (sheetWindowStart > 0) {
        const end = Math.min(sheetTotalRows, sheetWindowStart + Math.max(0, countDataRows()));
        hint.textContent = `${(sheetWindowStart + 1).toLocaleString("ko-KR")}~${end.toLocaleString("ko-KR")} / ${sheetTotalRows.toLocaleString("ko-KR")}행 · 위로 스크롤하면 이전 불러옴`;
      } else {
        hint.textContent = `${sheetServerLoadedCount.toLocaleString("ko-KR")} / ${sheetTotalRows.toLocaleString("ko-KR")}행 · 스크롤하면 더 불러옴`;
      }
    } else if (!hint.textContent || hint.textContent.includes("미반영") || hint.textContent.includes("스크롤") || hint.textContent.includes("로드 오류") || hint.textContent.includes("마이그레이션") || hint.textContent.includes("이전 불러옴")) {
      hint.textContent = "기입·붙여넣기 후 「입력 반영」";
    }
  }
  if (btn) {
    btn.disabled = !sheetDirty || persistBusy || sheetLoadError;
    btn.classList.toggle("is-dirty", sheetDirty && !persistBusy && !sheetLoadError);
  }
}

function markSheetDirty() {
  sheetDirty = true;
  updateDirtyUi();
}

function markSheetClean(msg) {
  sheetDirty = false;
  updateDirtyUi();
  if (msg) flashSaveHint(msg);
}

function showSavingModal(title, hint) {
  if (typeof window.showHubBusy === "function") {
    window.showHubBusy(
      title || "저장 중…",
      hint || "서버에 반영하고 있습니다. 잠시만 기다려 주세요."
    );
    return;
  }
  const modal = document.getElementById("savingModal");
  const titleEl = document.getElementById("savingTitle");
  const hintEl = document.getElementById("savingHint");
  if (titleEl) titleEl.textContent = title || "저장 중…";
  if (hintEl) {
    hintEl.textContent =
      hint || "서버에 반영하고 있습니다. 잠시만 기다려 주세요.";
  }
  if (modal) modal.hidden = false;
}

function hideSavingModal() {
  if (typeof window.forceHideHubBusy === "function") {
    window.forceHideHubBusy();
    return;
  }
  if (typeof window.hideHubBusy === "function") {
    window.hideHubBusy();
    return;
  }
  const modal = document.getElementById("savingModal");
  if (modal) modal.hidden = true;
}

async function persistWorking(options = {}) {
  const {
    title = "저장 중…",
    hint = "서버에 반영하고 있습니다. 잠시만 기다려 주세요.",
    successMsg,
    skipEnsureFull = false,
    
    forceReplace = false,
  } = options;
  if (persistBusy) return false;
  persistBusy = true;
  updateDirtyUi();
  showSavingModal(title, hint);
  try {
    if (forceReplace) {
      sheetLoadError = false;
      sheetFullyLoaded = true;
      sheetServerLoadedCount = workingRows.length;
      sheetTotalRows = workingRows.length;
    } else if (!skipEnsureFull) {
      if (sheetLoadError) {
        throw new Error(
          "시트 일부를 불러오지 못한 상태입니다.\n" +
            "① 새로고침 후 다시 시도하거나\n" +
            "② 엑셀 업로드 → 「전체 교체」로 마이그레이션하세요."
        );
      }
      if (!sheetFullyLoaded) {
        const hintEl = document.getElementById("savingHint");
        if (hintEl) hintEl.textContent = "저장 전 나머지 행을 불러오는 중…";
        const ok = await ensureSheetFullyLoaded({ quiet: true });
        if (!ok || !sheetFullyLoaded) {
          throw new Error(
            "전체 행을 불러오지 못해 저장을 막았습니다.\n" +
              "대량 레거시 시트면 엑셀 「전체 교체」로 다시 올려 주세요."
          );
        }
      }
      const dataCount = countDataRows();
      if (sheetTotalRows > 0 && dataCount < sheetTotalRows) {
        throw new Error(
          `로드된 행(${dataCount})이 서버 행수(${sheetTotalRows})보다 적어 저장을 막았습니다.`
        );
      }
    }
    const rowsToSave = stripTrailingBlankRows(workingRows);
    await Repository.replaceSheet(currentBrand, currentSheetId, rowsToSave, {
      onProgress: (msg) => {
        const hintEl = document.getElementById("savingHint");
        if (hintEl && msg) hintEl.textContent = msg;
      },
    });
    workingRows = rowsToSave.slice();
    sheetWindowStart = 0;
    sheetTotalRows = workingRows.length;
    sheetServerLoadedCount = workingRows.length;
    sheetFullyLoaded = true;
    sheetLoadError = false;
    ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY);
    pendingScrollToEnd = true;
    renderSheet();
    await renderAuditLogs();
    markSheetClean(
      successMsg || `저장됨 · ${rowsToSave.length}행 · ${new Date().toLocaleTimeString("ko-KR")}`
    );
    return true;
  } catch (err) {
    console.error("[Admin] persist failed", err);
    flashSaveHint("저장 실패 · 권한/네트워크 확인");
    updateDirtyUi();
    alert("서버 저장에 실패했습니다.\n" + (err?.message || String(err)));
    return false;
  } finally {
    persistBusy = false;
    hideSavingModal();
    updateDirtyUi();
  }
}

async function applySheetChanges() {
  if (!sheetDirty) {
    flashSaveHint("반영할 변경이 없습니다");
    return;
  }
  const ok = await persistWorking({
    title: "입력 반영 중…",
    hint: `「${sheetDef()?.label || currentSheetId}」 ${countDataRows()}행을 서버에 저장합니다.`,
    successMsg: `입력 반영 완료 · ${countDataRows()}행`,
  });
  if (ok && typeof Repository.notifyChanged === "function") {
    
  }
}

async function refreshBrandList() {
  brandList = await Repository.getBrands();
}

async function openBrandModal() {
  try {

    const brandId =
      (typeof SheetSchema !== "undefined" && SheetSchema.DEFAULT_BRAND_SLUG) || "dreame";
    const brandName =
      (typeof SheetSchema !== "undefined" && SheetSchema.DEFAULT_BRAND_NAME) || "드리미";
    brandList = [{ id: brandId, name: brandName, slug: brandId }];
    renderBrandList();
    const modal = document.getElementById("brandModal");
    if (!modal) {
      alert("브랜드 선택 창을 찾지 못했습니다.");
      return;
    }
    modal.hidden = false;
    document.body.style.overflow = "hidden";

    if (typeof Repository !== "undefined" && typeof Repository.ensureDefaultBrand === "function") {
      void Repository.ensureDefaultBrand().catch((err) =>
        console.warn("[Admin] ensureDefaultBrand", err)
      );
    }
  } catch (error) {
    console.error("[Admin] openBrandModal failed", error);
    alert("어드민을 열 수 없습니다.\n" + (error?.message || String(error)));
  }
}

function closeBrandModal() {
  document.getElementById("brandModal").hidden = true;
  if (document.getElementById("adminView").hidden) {
    document.body.style.overflow = "";
  }
}

function renderBrandList() {
  const list = document.getElementById("brandList");
  if (!list) return;
  const defaultSlug = SheetSchema.DEFAULT_BRAND_SLUG;
  if (!brandList.length) {
    brandList = [
      {
        id: defaultSlug,
        name: SheetSchema.DEFAULT_BRAND_NAME || "드리미",
        slug: defaultSlug,
      },
    ];
  }
  list.innerHTML = brandList
    .map(
      (b) => `
      <button type="button" class="brand-pick ${b.id === currentBrand ? "is-active" : ""}" data-brand="${escapeAttr(b.id)}">
        <strong>${escapeHtml(b.name)}</strong>
        <span>${b.id === defaultSlug ? "시트 5종 · Raw 연동" : escapeHtml(b.slug || b.id)}</span>
      </button>`
    )
    .join("");
  list.querySelectorAll("[data-brand]").forEach((btn) => {
    btn.addEventListener("click", () => {
      enterAdmin(btn.dataset.brand).catch((err) => console.error(err));
    });
  });
}

async function enterAdmin(brand) {
  currentBrand = brand;
  currentSheetId = "promo";
  closeBrandModal();
  const shell = document.getElementById("shell");
  if (shell) shell.hidden = true;
  document.getElementById("adminView").hidden = false;
  document.body.style.overflow = "hidden";
  document.getElementById("adminBrandLabel").textContent =
    brandList.find((item) => item.id === brand)?.name ||
    SheetSchema.DEFAULT_BRAND_NAME ||
    brand;
  renderSheetTabs();

  workingRows = SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
  renderSheet();
  try {
    await loadWorkingSheet();
  } catch (error) {
    console.warn("[Admin] sheet load failed, keep schema columns", error);
    workingRows = SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
    renderSheet();
  }
}

function exitAdmin() {
  if (sheetDirty && !confirm("반영하지 않은 변경이 있습니다.\n저장하지 않고 대시보드로 돌아갈까요?")) {
    return;
  }
  sheetDirty = false;
  updateDirtyUi();
  document.getElementById("adminView").hidden = true;
  const shell = document.getElementById("shell");
  if (shell) shell.hidden = false;
  document.body.style.overflow = "";
  Repository.notifyChanged({ action: "exitAdmin", brandId: currentBrand });
  if (typeof window.refreshBrandNav === "function") window.refreshBrandNav();
}

function renderSheetTabs() {
  const nav = document.getElementById("sheetTabs");
  nav.innerHTML = SheetSchema.SHEET_DEFS.map(
    (s) => `
    <button type="button" class="sheet-tab ${s.id === currentSheetId ? "is-active" : ""}" data-sheet="${s.id}">
      ${s.label}
    </button>`
  ).join("");
  nav.querySelectorAll("[data-sheet]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (btn.dataset.sheet === currentSheetId) return;
      if (
        sheetDirty &&
        !confirm("반영하지 않은 변경이 있습니다.\n저장하지 않고 다른 시트로 이동할까요?")
      ) {
        return;
      }
      sheetDirty = false;
      currentSheetId = btn.dataset.sheet;
      renderSheetTabs();
      workingRows = SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
      renderSheet();
      updateDirtyUi();
      await loadWorkingSheet();
    });
  });
}

function normalizeWorkingRows(rows, colCount) {
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) {
    return SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
  }
  return list.map((row) => {
    const cells = Array.isArray(row) ? row : [];
    return Array.from({ length: colCount }, (_, i) => String(cells[i] ?? ""));
  });
}

function resetSheetPaging() {
  sheetTotalRows = 0;
  sheetServerLoadedCount = 0;
  sheetWindowStart = 0;
  sheetFullyLoaded = true;
  sheetPageLoading = false;
  sheetLoadError = false;
}

function countTrailingBlanks(rows = workingRows) {
  let n = 0;
  for (let i = rows.length - 1; i >= 0; i--) {
    if (!isBlankSheetRow(rows[i])) break;
    n += 1;
  }
  return n;
}

function countDataRows(rows = workingRows) {
  return Math.max(0, rows.length - countTrailingBlanks(rows));
}

function stripTrailingBlankRows(rows) {
  const out = Array.isArray(rows) ? rows.slice() : [];
  while (out.length && isBlankSheetRow(out[out.length - 1])) out.pop();
  return out;
}


function ensureTrailingEmptyRows(n = SHEET_TRAIL_EMPTY) {
  const def = sheetDef();
  if (!def) return false;
  let changed = false;
  let trailing = countTrailingBlanks();
  if (!workingRows.length) {
    workingRows = SheetSchema.emptySheetRows(currentSheetId, n);
    return true;
  }
  while (trailing < n) {
    workingRows.push(SheetSchema.emptyRow(def.cols));
    trailing += 1;
    changed = true;
  }
  while (trailing > n && workingRows.length > n) {
    workingRows.pop();
    trailing -= 1;
    changed = true;
  }
  return changed;
}

function scrollSheetToEnd() {
  const wrap = document.querySelector(".sheet-wrap");
  if (!wrap) return;
  requestAnimationFrame(() => {
    wrap.scrollTop = wrap.scrollHeight;
    requestAnimationFrame(() => {
      wrap.scrollTop = wrap.scrollHeight;
    });
  });
}

async function loadNextSheetPage() {
  if (sheetFullyLoaded || sheetPageLoading || sheetLoadError) return false;
  if (sheetDirty) return false;
  const def = sheetDef();
  if (!def) return false;
  sheetPageLoading = true;
  try {
    const page = await Repository.getSheetPage(currentBrand, currentSheetId, {
      offset: sheetServerLoadedCount,
      limit: SHEET_PAGE_SIZE,
    });
    const next = Array.isArray(page.rows)
      ? page.rows.map((row) =>
          Array.from({ length: def.cols.length }, (_, i) =>
            String((Array.isArray(row) ? row : [])[i] ?? "")
          )
        )
      : [];
    workingRows = workingRows.slice(0, sheetServerLoadedCount).concat(next);
    sheetServerLoadedCount += next.length;
    sheetTotalRows = Number(page.total) || sheetTotalRows;
    const hasMore = page.hasMore === true || sheetServerLoadedCount < sheetTotalRows;
    if (next.length === 0 && hasMore) {
      sheetLoadError = true;
      sheetFullyLoaded = false;
      console.warn("[Admin] 빈 페이지인데 hasMore — 로드 중단", {
        loaded: sheetServerLoadedCount,
        total: sheetTotalRows,
      });
      updateDirtyUi();
      return false;
    }
    sheetFullyLoaded = !hasMore || sheetServerLoadedCount >= sheetTotalRows;
    if (!workingRows.length) {
      workingRows = SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
      sheetFullyLoaded = true;
      sheetTotalRows = 0;
    }
    ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY);
    renderSheet();
    updateDirtyUi();
    return next.length > 0;
  } catch (error) {
    console.warn("[Admin] loadNextSheetPage failed", error);
    sheetLoadError = true;
    sheetFullyLoaded = false;
    updateDirtyUi();
    return false;
  } finally {
    sheetPageLoading = false;
  }
}


async function ensureSheetFullyLoaded(options = {}) {
  const quiet = options.quiet === true;
  if (sheetFullyLoaded && !sheetLoadError) return true;
  if (sheetLoadError) return false;
  const def = sheetDef();
  if (!def) return false;


  try {
    if (!quiet) showSavingModal("전체 행 로드…", "시트를 한 번에 불러오는 중…");
    else {
      const hintEl = document.getElementById("savingHint");
      if (hintEl) hintEl.textContent = "저장 전 전체 행을 한 번에 불러오는 중…";
    }
    const full = await Repository.getSheet(currentBrand, currentSheetId);
    const rows = normalizeWorkingRows(
      Array.isArray(full?.rows) ? full.rows : [],
      def.cols.length
    );
    const localDirty = sheetDirty;
    const winStart = sheetWindowStart;
    const localData = stripTrailingBlankRows(workingRows);

    if (localDirty && localData.length && !sheetFullyLoaded) {
      if (winStart > 0) {
        workingRows = rows.slice(0, winStart).concat(localData);
      } else if (localData.length >= rows.length) {
        workingRows = localData.slice();
      } else {
        workingRows = localData.concat(rows.slice(localData.length));
      }
    } else {
      workingRows = rows;
    }
    if (!workingRows.length) {
      workingRows = SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
    }
    sheetWindowStart = 0;
    sheetServerLoadedCount = countDataRows();
    sheetTotalRows = countDataRows();
    sheetFullyLoaded = true;
    sheetLoadError = false;
    ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY);
    pendingScrollToEnd = true;
    renderSheet();
    updateDirtyUi();
    return true;
  } catch (error) {
    console.warn("[Admin] ensureSheetFullyLoaded getSheet failed", error);
    const code = error?.code || "";
    if (code === "legacy-too-large") {
      sheetLoadError = true;
      flashSaveHint("레거시 과다 · 엑셀 「전체 교체」로 마이그레이션");
      if (!quiet) {
        alert(
          "예전 행=문서 데이터가 너무 많아 전부 불러올 수 없습니다.\n\n" +
            "엑셀 업로드 → 「전체 교체」로 다시 올려 주세요. (chunks로 이전됩니다)"
        );
      }
      return false;
    }

    let guard = 0;
    while (!sheetFullyLoaded && !sheetLoadError && guard < 200) {
      guard += 1;
      const before = sheetServerLoadedCount;
      const got = await loadNextSheetPage();
      if (sheetLoadError) return false;
      if (sheetFullyLoaded) return true;
      if (!got && sheetServerLoadedCount === before) {
        sheetLoadError = true;
        return false;
      }
    }
    return sheetFullyLoaded && !sheetLoadError;
  } finally {
    if (!quiet) hideSavingModal();
  }
}

async function loadPrevSheetPage() {
  if (sheetWindowStart <= 0 || sheetPageLoading || sheetLoadError) return false;
  if (sheetDirty) return false;
  const def = sheetDef();
  if (!def) return false;
  sheetPageLoading = true;
  const wrap = document.querySelector(".sheet-wrap");
  const prevHeight = wrap ? wrap.scrollHeight : 0;
  const prevTop = wrap ? wrap.scrollTop : 0;
  try {
    const newStart = Math.max(0, sheetWindowStart - SHEET_PAGE_SIZE);
    const limit = sheetWindowStart - newStart;
    if (limit <= 0) return false;
    const page = await Repository.getSheetPage(currentBrand, currentSheetId, {
      offset: newStart,
      limit,
    });
    const prev = Array.isArray(page.rows)
      ? page.rows.map((row) =>
          Array.from({ length: def.cols.length }, (_, i) =>
            String((Array.isArray(row) ? row : [])[i] ?? "")
          )
        )
      : [];
    const dataOnly = stripTrailingBlankRows(workingRows);
    workingRows = prev.concat(dataOnly);
    sheetWindowStart = newStart;
    sheetServerLoadedCount = sheetWindowStart + dataOnly.length + prev.length;
    if (sheetWindowStart === 0 && sheetServerLoadedCount >= sheetTotalRows) {
      sheetFullyLoaded = true;
    }
    ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY);
    renderSheet();
    if (wrap) {
      requestAnimationFrame(() => {
        const delta = wrap.scrollHeight - prevHeight;
        wrap.scrollTop = prevTop + Math.max(0, delta);
      });
    }
    updateDirtyUi();
    return prev.length > 0;
  } catch (error) {
    console.warn("[Admin] loadPrevSheetPage failed", error);
    return false;
  } finally {
    sheetPageLoading = false;
  }
}

async function loadWorkingSheet() {
  const def = sheetDef();
  if (!def) return;
  resetSheetPaging();
  sheetFullyLoaded = false;
  try {
    const probe = await Repository.getSheetPage(currentBrand, currentSheetId, {
      offset: 0,
      limit: SHEET_PAGE_SIZE,
    });
    const probeRows = Array.isArray(probe.rows) ? probe.rows : [];
    sheetTotalRows = Number(probe.total) || probeRows.length;

    if (!probeRows.length && !(Number(probe.total) > 0)) {
      workingRows = SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
      sheetServerLoadedCount = 0;
      sheetWindowStart = 0;
      sheetTotalRows = 0;
      sheetFullyLoaded = true;
      pendingScrollToEnd = true;
      if (probe.staleMeta) {
        flashSaveHint("청크 없음 · 엑셀 「전체 교체」로 채워 주세요");
      }
    } else if (!probeRows.length && Number(probe.total) > 0) {
      sheetLoadError = true;
      workingRows = SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
      sheetFullyLoaded = false;
      flashSaveHint("시트 첫 페이지 로드 실패 · 엑셀 전체 교체로 마이그레이션");
    } else if (sheetTotalRows > SHEET_PAGE_SIZE) {
      const start = Math.max(0, sheetTotalRows - SHEET_PAGE_SIZE);
      const lastPage = await Repository.getSheetPage(currentBrand, currentSheetId, {
        offset: start,
        limit: SHEET_PAGE_SIZE,
      });
      const rows = Array.isArray(lastPage.rows) ? lastPage.rows : [];
      workingRows = normalizeWorkingRows(rows, def.cols.length);
      sheetWindowStart = start;
      sheetServerLoadedCount = start + workingRows.length;
      sheetTotalRows = Number(lastPage.total) || sheetTotalRows;
      sheetFullyLoaded = start === 0 && sheetServerLoadedCount >= sheetTotalRows;
      pendingScrollToEnd = true;
    } else {
      workingRows = normalizeWorkingRows(probeRows, def.cols.length);
      sheetWindowStart = 0;
      sheetServerLoadedCount = workingRows.length;
      sheetFullyLoaded =
        sheetServerLoadedCount >= sheetTotalRows || probe.hasMore === false;
      pendingScrollToEnd = true;
    }
  } catch (error) {
    console.warn("[Admin] getSheetPage failed", error);
    sheetLoadError = true;
    workingRows = SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
    sheetFullyLoaded = false;
    sheetTotalRows = 0;
    sheetServerLoadedCount = 0;
    sheetWindowStart = 0;
    const msg =
      error?.code === "legacy-too-large"
        ? "레거시 과다 · 엑셀 「전체 교체」로 마이그레이션"
        : "시트 로드 실패 · 엑셀 「전체 교체」는 가능";
    flashSaveHint(msg);
  }
  ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY);
  sheetDirty = false;
  updateDirtyUi();
  renderSheet();
  try {
    await renderAuditLogs();
  } catch (error) {
    console.warn("[Admin] audit load failed", error);
  }
}

function onSheetWrapScroll() {
  const wrap = document.querySelector(".sheet-wrap");
  if (!wrap || sheetPageLoading || persistBusy || sheetDirty || sheetLoadError) {
    return;
  }
  if (sheetWindowStart > 0 && wrap.scrollTop < 120) {
    loadPrevSheetPage().catch((err) => console.warn(err));
    return;
  }
  if (sheetFullyLoaded) return;
  if (sheetWindowStart > 0) return;
  if (wrap.scrollTop + wrap.clientHeight < wrap.scrollHeight - 160) return;
  loadNextSheetPage().catch((err) => console.warn(err));
}

async function ensureEditableSheet() {
  if (sheetFullyLoaded && !sheetLoadError) return true;
  flashSaveHint("편집 전 전체 행 불러오는 중…");
  const ok = await ensureSheetFullyLoaded();
  if (!ok) {
    alert("전체 행을 불러오지 못했습니다.\n부분 편집·저장 시 데이터가 지워질 수 있어 막았습니다.");
    return false;
  }
  renderSheet();
  return true;
}

function summarizeAuditAction(entry) {
  const def =
    typeof SheetSchema !== "undefined" && entry?.sheetId
      ? SheetSchema.getSheetDef(entry.sheetId)
      : null;
  const sheetLabel = def?.label || entry?.sheetId || "";
  const action = String(entry?.action || "");
  if (action === "replaceSheet") {
    return sheetLabel ? `${sheetLabel} 저장` : "시트 저장";
  }
  if (action === "createBrand") {
    return "브랜드 생성";
  }
  if (action === "upsertRows") {
    return sheetLabel ? `${sheetLabel} 수정` : "시트 수정";
  }
  return sheetLabel ? `${sheetLabel} · ${action || "변경"}` : action || "변경";
}

async function renderAuditLogs() {
  const list = document.getElementById("auditList");
  if (!list) return;
  if (typeof Repository.getAuditLogs !== "function") {
    list.innerHTML = "<li>현재 Repository는 audit 조회를 지원하지 않습니다.</li>";
    return;
  }
  let logs;
  try {
    logs = await Repository.getAuditLogs(currentBrand, 10);
  } catch (error) {
    console.error("[Admin] audit log load failed", error);
    list.innerHTML = "<li>변경 로그를 불러오지 못했습니다.</li>";
    return;
  }
  list.innerHTML = logs.length
    ? logs
        .map((entry) => {
          const who = String(entry.email || "").trim() || "알 수 없음";
          const what = summarizeAuditAction(entry);
          return `<li><strong>${escapeHtml(who)}</strong> · ${escapeHtml(what)}</li>`;
        })
        .join("")
    : "<li>변경 로그가 없습니다.</li>";
}

function renderSheet() {
  const def = sheetDef();
  const head = document.getElementById("sheetHead");
  const body = document.getElementById("sheetBody");
  if (!def || !head || !body) {
    console.error("[Admin] sheetDef/DOM missing", { def: !!def, head: !!head, body: !!body });
    return;
  }
  if (!workingRows.length) {
    workingRows = SheetSchema.emptySheetRows(def.id, SHEET_TRAIL_EMPTY);
  }
  workingRows = normalizeWorkingRows(workingRows, def.cols.length);
  ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY);

  const dataCount = countDataRows();
  const absStart = sheetWindowStart + 1;
  const absDataEnd = sheetWindowStart + dataCount;
  const trailCount = Math.max(0, workingRows.length - dataCount);
  const rangeNote =
    sheetTotalRows > 0
      ? `전체 ${sheetTotalRows.toLocaleString("ko-KR")}행 중 ${absStart.toLocaleString("ko-KR")}–${Math.max(absStart, absDataEnd).toLocaleString("ko-KR")}행`
      : "새 시트 · 입력 대기";

  head.innerHTML =
    `<tr><th class="row-num" title="${escapeHtml(rangeNote)}">행번호</th>${def.cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;

  body.innerHTML = workingRows
    .map((row, ri) => {
      const absNo = sheetWindowStart + ri + 1;
      const isTrail = ri >= dataCount;
      return `
      <tr${isTrail ? ' class="is-trail-row"' : ""}>
        <td class="row-num${isTrail ? " is-trail" : ""}" title="${isTrail ? `입력용 빈 행 (${absNo.toLocaleString("ko-KR")})` : `전체 기준 ${absNo.toLocaleString("ko-KR")}번째 행`}">${absNo.toLocaleString("ko-KR")}</td>
        ${def.cols
          .map((_, ci) => {
            const val = row[ci] ?? "";
            return `<td contenteditable="true" spellcheck="false" data-r="${ri}" data-c="${ci}">${escapeHtml(String(val))}</td>`;
          })
          .join("")}
      </tr>`;
    })
    .join("");

  const rangeEl = document.getElementById("sheetRangeHint");
  if (rangeEl) {
    const parts = [rangeNote];
    if (sheetTotalRows > 0 && sheetWindowStart > 0) {
      parts.push("끝에서 불러옴 · 위로 스크롤하면 이전 구간");
    } else if (sheetTotalRows > 0 && !sheetFullyLoaded && sheetWindowStart === 0) {
      parts.push("아래로 스크롤하면 더 불러옴");
    }
    if (trailCount > 0) {
      parts.push(`아래 입력용 빈 행 ${trailCount}개 (저장 시 제외)`);
    }
    rangeEl.textContent = parts.join(" · ");
  }

  bindSheetCells();
  if (pendingScrollToEnd) {
    pendingScrollToEnd = false;
    scrollSheetToEnd();
  }
}

function bindSheetCells() {
  const tbody = document.getElementById("sheetBody");
  if (!tbody) return;
  tbody.querySelectorAll("td[contenteditable]").forEach((td) => {
    td.addEventListener("focus", () => {
      activeCell = td;
    });
    td.addEventListener("blur", () => {
      commitCell(td);
    });
    td.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        td.blur();
        focusNeighbor(td, 1, 0);
      } else if (e.key === "Tab") {
        e.preventDefault();
        commitCell(td);
        focusNeighbor(td, 0, e.shiftKey ? -1 : 1);
      }
    });
  });
}

function readClipboardPlainText(e) {
  const clip = e?.clipboardData || window.clipboardData;
  if (!clip) return "";
  try {
    const plain = clip.getData("text/plain") || clip.getData("Text") || "";
    if (plain) return plain;
  } catch {
    
  }
  try {
    const html = clip.getData("text/html") || "";
    if (!html) return "";
    const doc = new DOMParser().parseFromString(html, "text/html");
    const rows = [...doc.querySelectorAll("tr")];
    if (!rows.length) return "";
    return rows
      .map((tr) =>
        [...tr.querySelectorAll("th,td")]
          .map((cell) => cell.textContent.replace(/\r?\n/g, " ").trim())
          .join("\t")
      )
      .join("\n");
  } catch {
    return "";
  }
}

function handlePaste(td, e) {
  e.preventDefault();
  e.stopPropagation();
  const text = readClipboardPlainText(e);
  if (!text) return;

  const matrix = text
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .filter((line, i, arr) => !(i === arr.length - 1 && line === ""))
    .map((line) => line.split("\t"));

  if (!matrix.length) return;

  const startR = Number(td.dataset.r);
  const startC = Number(td.dataset.c);
  const def = sheetDef();
  if (!def) return;

  void (async () => {
    if (!(await ensureEditableSheet())) return;
    matrix.forEach((cols, ri) => {
      const r = startR + ri;
      while (workingRows.length <= r) {
        workingRows.push(SheetSchema.emptyRow(def.cols));
      }
      if (!Array.isArray(workingRows[r])) {
        workingRows[r] = SheetSchema.emptyRow(def.cols);
      }
      cols.forEach((val, ci) => {
        const c = startC + ci;
        if (c >= def.cols.length) return;
        workingRows[r][c] = val;
      });
      autoCalcRaw(workingRows, r);
    });

    ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY);
    renderSheet();
    const focus = document.querySelector(
      `#sheetBody td[data-r="${startR}"][data-c="${startC}"]`
    );
    if (focus) focus.focus();
    markSheetDirty();
    flashSaveHint("붙여넣기됨 · 「입력 반영」으로 저장");
  })();
}

function commitCell(td) {
  const r = Number(td.dataset.r);
  const c = Number(td.dataset.c);
  const text = td.innerText.replace(/\u00a0/g, " ").trimEnd();
  if ((workingRows[r][c] ?? "") !== text) {
    workingRows[r][c] = text;
    autoCalcRaw(workingRows, r);
    markSheetDirty();
    if (currentSheetId === "raw") refreshRow(r);
  }
  if (ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY)) {
    const focusR = r;
    const focusC = c;
    renderSheet();
    const cell = document.querySelector(
      `#sheetBody td[data-r="${focusR}"][data-c="${focusC}"]`
    );
    if (cell) cell.focus();
  }
}

function autoCalcRaw(rows, r) {
  if (currentSheetId !== "raw") return;
  const row = rows[r];
  const ship = row[4];
  const qty = Number(String(row[3]).replace(/,/g, "")) || 0;
  const price = Number(String(row[11]).replace(/,/g, "")) || 0;
  if (ship && /^\d{4}-\d{2}-\d{2}$/.test(ship)) {
    const d = new Date(ship + "T00:00:00");
    if (!Number.isNaN(d.getTime())) {
      row[6] = String(d.getFullYear());
      row[7] = String(d.getMonth() + 1);
      row[8] = String(isoWeek(d));
    }
  }
  if (qty || price) {
    const existing = Number(String(row[12] ?? "").replace(/,/g, "")) || 0;
    if (!existing) row[12] = String(qty * price);
  }
}

function isoWeek(date) {
  const t = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - yearStart) / 86400000 + 1) / 7);
}

function refreshRow(r) {
  const tr = document.getElementById("sheetBody").rows[r];
  if (!tr) return;
  workingRows[r].forEach((val, ci) => {
    const td = tr.cells[ci + 1];
    if (td && document.activeElement !== td) td.textContent = val ?? "";
  });
}

function focusNeighbor(td, dRow, dCol) {
  const r = Number(td.dataset.r) + dRow;
  const c = Number(td.dataset.c) + dCol;
  const next = document.querySelector(`#sheetBody td[data-r="${r}"][data-c="${c}"]`);
  if (next) {
    next.focus();
    selectCellContents(next);
  }
}

function selectCellContents(td) {
  const range = document.createRange();
  range.selectNodeContents(td);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

async function addRow() {
  if (!(await ensureEditableSheet())) return;
  ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY);
  pendingScrollToEnd = true;
  renderSheet();
  const focusR = countDataRows();
  const cell = document.querySelector(`#sheetBody td[data-r="${focusR}"][data-c="0"]`);
  if (cell) cell.focus();
}

async function clearSheet() {
  const label = sheetDef().label;
  const brand = currentBrand;
  const knownCount = Math.max(workingRows.length, sheetTotalRows);
  if (!confirm(`[1/3] 「${brand}」·「${label}」시트를 비울까요?`)) return;
  if (!confirm(`[2/3] 이 작업은 되돌릴 수 없습니다.\n현재 약 ${knownCount}행이 삭제됩니다. 계속할까요?`)) return;
  if (
    !confirm(
      `[3/3] 최종 확정\n\n브랜드: ${brand}\n시트: ${label}\n\n정말 시트를 비우겠습니까?`
    )
  ) {
    return;
  }
  workingRows = SheetSchema.emptySheetRows(currentSheetId, SHEET_TRAIL_EMPTY);
  sheetTotalRows = 0;
  sheetServerLoadedCount = 0;
  sheetWindowStart = 0;
  sheetFullyLoaded = true;
  pendingScrollToEnd = true;
  renderSheet();
  await persistWorking({
    title: "시트 비우는 중…",
    hint: "서버에서 시트 내용을 지우고 있습니다.",
    successMsg: "시트 비움 · 저장됨",
    skipEnsureFull: true,
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

function normalizeHeader(h) {
  return String(h ?? "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function excelSerialToYmd(n) {
  const excelEpoch = new Date(Date.UTC(1899, 11, 30));
  const d = new Date(excelEpoch.getTime() + Number(n) * 86400000);
  if (Number.isNaN(d.getTime())) return String(n);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

function cellToString(v) {
  if (v == null || v === "") return "";
  if (typeof v === "number") {
    if (v > 20000 && v < 80000 && Number.isInteger(v)) return excelSerialToYmd(v);
    return String(v);
  }
  if (v instanceof Date) {
    return `${v.getFullYear()}-${String(v.getMonth() + 1).padStart(2, "0")}-${String(v.getDate()).padStart(2, "0")}`;
  }
  return String(v).trim();
}

function mapExcelToSheet(matrix, cols) {
  if (!matrix.length) return { rows: [], usePositional: true, mappedCount: 0 };
  const header = matrix[0].map(normalizeHeader);
  const colNorm = cols.map(normalizeHeader);
  const indexes = colNorm.map((c) => {
    let idx = header.indexOf(c);
    if (idx >= 0) return idx;
    idx = header.findIndex((h) => h === c || h.includes(c) || c.includes(h));
    return idx;
  });
  const mappedCount = indexes.filter((i) => i >= 0).length;
  const usePositional = mappedCount < Math.ceil(cols.length * 0.4);

  const out = [];
  for (let r = 1; r < matrix.length; r++) {
    const src = matrix[r] || [];
    if (src.every((c) => cellToString(c) === "")) continue;
    const row = cols.map((_, ci) => {
      if (usePositional) return cellToString(src[ci]);
      const idx = indexes[ci];
      return idx >= 0 ? cellToString(src[idx]) : "";
    });
    out.push(row);
  }
  return { rows: out, usePositional, mappedCount };
}


let pendingExcelMode = null;

function openExcelModeModal() {
  const hint = document.getElementById("excelModeSheetHint");
  if (hint) {
    hint.textContent = `브랜드 「${currentBrand}」 · 「${sheetDef().label}」 · 현재 ${workingRows.length}행`;
  }
  document.getElementById("excelModeModal").hidden = false;
}

function closeExcelModeModal() {
  document.getElementById("excelModeModal").hidden = true;
}

function chooseExcelMode(mode) {
  pendingExcelMode = mode === "append" ? "append" : "replace";
  closeExcelModeModal();
  const fileInput = document.getElementById("excelFileInput");
  fileInput.value = "";
  fileInput.click();
}

function isBlankSheetRow(row) {
  return !row || row.every((c) => String(c ?? "").trim() === "");
}

async function handleExcelUpload(file) {
  if (!file) {
    pendingExcelMode = null;
    return;
  }
  const mode = pendingExcelMode;
  pendingExcelMode = null;
  if (mode !== "append" && mode !== "replace") {
    alert("업로드 방식(추가/교체)을 먼저 선택해 주세요.");
    return;
  }
  if (typeof XLSX === "undefined") {
    alert("엑셀 라이브러리를 불러오지 못했습니다. 네트워크를 확인해 주세요.");
    return;
  }
  const def = sheetDef();
  const buf = await file.arrayBuffer();
  const wb = XLSX.read(buf, { type: "array", cellDates: true });
  const ws = wb.Sheets[wb.SheetNames[0]];
  const matrix = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "", raw: true });
  const { rows, usePositional, mappedCount } = mapExcelToSheet(matrix, def.cols);

  if (!rows.length) {
    alert("업로드할 데이터 행이 없습니다. 헤더 + 데이터 행이 있는지 확인해 주세요.");
    return;
  }

  const modeLabel = mode === "append" ? "기존 행에 추가" : "전체 교체";
  const currentKnown = Math.max(workingRows.length, sheetTotalRows);
  const afterCount =
    mode === "append"
      ? Math.max(
          workingRows.filter((r) => !isBlankSheetRow(r)).length,
          sheetTotalRows
        ) + rows.length
      : rows.length;
  const matchLine = usePositional
    ? `헤더 매칭이 적어(${mappedCount}/${def.cols.length}) 열 순서대로 넣습니다.`
    : `헤더 매칭 ${mappedCount}/${def.cols.length}`;

  const confirmMsg =
    `[최종 확정]\n\n` +
    `브랜드: ${currentBrand}\n` +
    `시트: ${def.label}\n` +
    `방식: ${modeLabel}\n` +
    `파일: ${file.name}\n` +
    `가져올 행: ${rows.length}행\n` +
    `현재 시트: 약 ${currentKnown}행 → 적용 후 약 ${afterCount}행\n` +
    `${matchLine}\n\n` +
    (mode === "replace"
      ? "⚠ 현재 시트 내용은 모두 사라지고 파일로 덮어씁니다.\n\n"
      : "기존 데이터는 유지되고 아래에 이어 붙입니다.\n\n") +
    `정말 확정할까요?`;

  if (!confirm(confirmMsg)) return;

  if (mode === "append") {
    if (sheetLoadError) {
      alert(
        "시트를 전부 불러오지 못한 상태라 「추가」는 위험합니다.\n\n" +
          "「전체 교체」로 다시 업로드해 주세요. (마이그레이션)"
      );
      return;
    }
    if (!sheetFullyLoaded) {
      showSavingModal("엑셀 준비 중…", "기존 행을 모두 불러온 뒤 이어 붙입니다.");
      try {
        const ok = await ensureSheetFullyLoaded({ quiet: true });
        if (!ok || sheetLoadError) {
          alert(
            "기존 행을 모두 불러오지 못했습니다.\n\n" +
              "「전체 교체」로 업로드해 주세요."
          );
          return;
        }
      } finally {
        hideSavingModal();
      }
    }
  }

  if (mode === "replace") {
    workingRows = rows.length ? rows : [SheetSchema.emptyRow(def.cols)];
    sheetLoadError = false;
    sheetFullyLoaded = true;
    sheetWindowStart = 0;
    sheetServerLoadedCount = workingRows.length;
    sheetTotalRows = workingRows.length;
  } else {
    const base = workingRows.filter((r) => !isBlankSheetRow(r));
    workingRows = base.concat(rows);
    if (!workingRows.length) workingRows = [SheetSchema.emptyRow(def.cols)];
    sheetFullyLoaded = true;
    sheetWindowStart = 0;
    sheetServerLoadedCount = workingRows.length;
    sheetTotalRows = workingRows.length;
  }
  if (currentSheetId === "raw") {
    workingRows.forEach((_, i) => autoCalcRaw(workingRows, i));
  }
  ensureTrailingEmptyRows(SHEET_TRAIL_EMPTY);
  pendingScrollToEnd = true;
  renderSheet();
  await persistWorking({
    title: "엑셀 반영 중…",
    hint:
      mode === "append"
        ? `${rows.length}행을 추가해 서버에 저장합니다.`
        : `${rows.length}행으로 시트를 교체해 서버에 저장합니다.`,
    successMsg:
      mode === "append"
        ? `엑셀 추가 ${rows.length}행 · 총 ${workingRows.length}행`
        : `엑셀 교체 ${rows.length}행`,
    forceReplace: mode === "replace",
    skipEnsureFull: mode === "replace",
  });
}

function downloadBlankTemplate() {
  if (typeof XLSX === "undefined") {
    alert("엑셀 라이브러리를 불러오지 못했습니다.");
    return;
  }
  const def = sheetDef();
  const aoa = [def.cols];
  const ws = XLSX.utils.aoa_to_sheet(aoa);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, def.label.slice(0, 31));
  XLSX.writeFile(wb, `${currentBrand}_${def.id}_양식.xlsx`);
}

async function downloadTemplate() {
  if (typeof XLSX === "undefined") {
    alert("엑셀 라이브러리를 불러오지 못했습니다.");
    return;
  }
  if (!sheetFullyLoaded) {
    showSavingModal("다운로드 준비…", "전체 행을 불러오는 중…");
    try {
      await ensureSheetFullyLoaded();
    } finally {
      hideSavingModal();
    }
  }
  const def = sheetDef();
  const aoa = [def.cols, ...workingRows];
  const ws = XLSX.utils.aoa_to_sheet(aoa);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, def.label.slice(0, 31));
  XLSX.writeFile(wb, `${currentBrand}_${def.id}.xlsx`);
}

document.addEventListener("DOMContentLoaded", initAdminUi);
if (document.readyState !== "loading") {
  initAdminUi();
}

function initAdminUi() {
  if (window.__eibeSalesAdminUiReady) return;
  window.__eibeSalesAdminUiReady = true;

  const adminBtn = document.getElementById("adminBtn");
  if (adminBtn) {
    adminBtn.hidden = false;
    adminBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openBrandModal().catch((error) => console.error(error));
    });
  }
  document.getElementById("brandClose")?.addEventListener("click", closeBrandModal);
  document.getElementById("brandModal")?.addEventListener("click", (e) => {
    if (e.target.id === "brandModal") closeBrandModal();
  });
  document.getElementById("adminBackBtn")?.addEventListener("click", exitAdmin);
  document.getElementById("applySheetBtn")?.addEventListener("click", () => {
    applySheetChanges().catch((err) => console.error(err));
  });
  document.getElementById("addRowBtn")?.addEventListener("click", () => addRow());
  document.getElementById("clearSheetBtn")?.addEventListener("click", () => clearSheet());
  updateDirtyUi();

  const fileInput = document.getElementById("excelFileInput");
  document.getElementById("excelTemplateBtn")?.addEventListener("click", () => downloadBlankTemplate());
  document.getElementById("excelUploadBtn")?.addEventListener("click", () => openExcelModeModal());
  document.getElementById("excelModeClose")?.addEventListener("click", closeExcelModeModal);
  document.getElementById("excelModeModal")?.addEventListener("click", (e) => {
    if (e.target.id === "excelModeModal") closeExcelModeModal();
  });
  document.getElementById("excelModeAppend")?.addEventListener("click", () => chooseExcelMode("append"));
  document.getElementById("excelModeReplace")?.addEventListener("click", () => chooseExcelMode("replace"));
  fileInput?.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    await handleExcelUpload(file);
    fileInput.value = "";
  });
  document.getElementById("excelDownloadBtn")?.addEventListener("click", () => {
    downloadTemplate().catch((err) => console.error(err));
  });

  const sheetTable = document.getElementById("sheetTable");
  if (sheetTable) {
    sheetTable.addEventListener("paste", (e) => {
      const td = e.target?.closest?.("td[contenteditable]");
      if (!td || !sheetTable.contains(td)) return;
      handlePaste(td, e);
    });
  }

  const sheetWrap = document.querySelector(".sheet-wrap");
  sheetWrap?.addEventListener("scroll", onSheetWrapScroll, { passive: true });
}

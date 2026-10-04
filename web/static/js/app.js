/**
 * EIBE SCM - Main JavaScript Module
 * Clean corporate design, no AI emojis
 */

const Loader = {
    show() {
        const loader = document.getElementById('global-loader');
        if (loader) loader.classList.add('active');
    },
    hide() {
        const loader = document.getElementById('global-loader');
        if (loader) loader.classList.remove('active');
    }
};

const API = {
    BASE: '',
    getToken() { return localStorage.getItem('scm_token'); },
    async request(endpoint, options = {}) {
        Loader.show();
        const token = this.getToken();
        const headers = { ...options.headers };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        try {
            const res = await fetch(`${this.BASE}${endpoint}`, { ...options, headers });
            if (res.status === 401) {
                Auth.redirectToLogin();
                throw new Error('Unauthorized');
            }
            if (res.status === 409) {
                const err = await res.json().catch(() => ({}));
                Toast.show(err.detail || '다른 사용자가 이미 수정했습니다. 새로고침 후 다시 시도하세요.', 'error');
                throw new Error(err.detail || 'Conflict');
            }
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `API Error: ${res.status}`);
            }
            return await res.json();
        } catch (error) {
            if (error.message !== 'Unauthorized' && error.message !== 'Conflict') {
                Toast.show(error.message, 'error');
            }
            throw error;
        } finally {
            Loader.hide();
        }
    },
    async get(endpoint) { return this.request(endpoint); },
    async post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
    },
    async postFormData(endpoint, formData) {
        Loader.show();
        const token = this.getToken();
        const headers = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        try {
            const res = await fetch(`${this.BASE}${endpoint}`, {
                method: 'POST',
                headers,
                body: formData
            });
            if (res.status === 401) {
                Auth.redirectToLogin();
                throw new Error('Unauthorized');
            }
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Upload Error: ${res.status}`);
            }
            return await res.json();
        } catch (error) {
            Toast.show(error.message, 'error');
            throw error;
        } finally {
            Loader.hide();
        }
    },
    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
};

const Auth = {
    init() {
        const isLoginPage = window.location.pathname === '/login';
        if (!this.isLoggedIn() && !isLoginPage) {
            this.redirectToLogin();
            return false;
        }
        if (this.isLoggedIn() && isLoginPage) {
            window.location.href = '/';
            return false;
        }
        this.updateSidebarUI();
        return true;
    },
    isLoggedIn() { return !!API.getToken(); },
    redirectToLogin() {
        localStorage.removeItem('scm_token');
        if (window.location.pathname !== '/login') {
            window.location.href = '/login';
        }
    },
    async login(username, password) {
        const formData = new URLSearchParams();
        formData.append('username', username);
        formData.append('password', password);
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData
            });
            if (!res.ok) throw new Error('로그인 실패');
            const data = await res.json();
            localStorage.setItem('scm_token', data.access_token);
            window.location.href = '/';
        } catch (err) {
            throw err;
        }
    },
    logout() {
        localStorage.removeItem('scm_token');
        window.location.href = '/login';
    },
    async updateSidebarUI() {
        const nameEl = document.getElementById('sidebar-user-name');
        const roleEl = document.getElementById('sidebar-user-role');
        const avatarEl = document.getElementById('sidebar-user-avatar');
        if (!nameEl) return;
        
        if (this.isLoggedIn()) {
            try {
                const user = await API.get('/api/auth/me');
                nameEl.textContent = user.name;
                roleEl.textContent = user.role;
                avatarEl.textContent = user.name.charAt(0);
                window._currentUserRole = user.role;
            } catch(e) {
                // Token might be expired
            }
        } else {
            nameEl.textContent = 'Guest';
            roleEl.textContent = '';
            avatarEl.textContent = '?';
        }
    }
};

const Format = {
    number(val) { return val == null || isNaN(val) ? '0' : Number(val).toLocaleString('ko-KR'); },
    currency(val) { return val == null || isNaN(val) ? '₩0' : '₩' + Number(val).toLocaleString('ko-KR'); },
    percent(val) { return val == null || isNaN(val) ? '0%' : Number(val).toFixed(1) + '%'; },

    _monthNamesEn: ['January','February','March','April','May','June','July','August','September','October','November','December'],
    _monthNamesShort: ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
    _dayNamesKr: ['일','월','화','수','목','금','토'],

    weekLabel(weekNum) {
        const d = new Date();
        d.setDate(d.getDate() + (weekNum - 1) * 7);
        const monthShort = this._monthNamesShort[d.getMonth()];
        const weekOfMonth = Math.ceil(d.getDate() / 7);
        return `${monthShort}-W${weekOfMonth}`;
    },
    weekLabels(count) {
        const labels = [];
        for (let i = 0; i < count; i++) {
            labels.push(this.weekLabel(i + 1));
        }
        return labels;
    },
    monthLabel(monthOffset) {
        const d = new Date();
        d.setMonth(d.getMonth() + monthOffset);
        return `${this._monthNamesShort[d.getMonth()]} ${d.getFullYear()}`;
    },
    today() {
        const d = new Date();
        const year = d.getFullYear();
        const month = d.getMonth() + 1;
        const day = d.getDate();
        const dayName = this._dayNamesKr[d.getDay()];
        return `${year}년 ${month}월 ${day}일 (${dayName})`;
    },
    todayShort() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    },
    dateTime(dateStr) {
        if (!dateStr) {
            const d = new Date();
            return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
        }
        return dateStr;
    },
    currentMonth() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
    },
    nextMonth() {
        const d = new Date();
        d.setMonth(d.getMonth() + 1);
        return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
    },
    nextMonthDisplay() {
        const d = new Date();
        d.setMonth(d.getMonth() + 1);
        return `${d.getFullYear()}년 ${d.getMonth()+1}월`;
    }
};

const Theme = {
    _initialized: false,
    init() {
        if (this._initialized) return;
        this._initialized = true;
        
        const authOk = Auth.init();
        if (authOk === false) return;
        
        const savedTheme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);
        this.updateToggleButton(savedTheme);
        Sidebar.init();
    },
    toggle() {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
        this.updateToggleButton(next);
        
        if (typeof Chart !== 'undefined') {
            const style = getComputedStyle(document.documentElement);
            Object.values(Chart.instances).forEach(chart => {
                chart.options.scales = chart.options.scales || {};
                Object.values(chart.options.scales).forEach(scale => {
                    if (scale.ticks) scale.ticks.color = style.getPropertyValue('--text-secondary').trim();
                    if (scale.grid) scale.grid.color = style.getPropertyValue('--border-default').trim();
                    if (scale.title) scale.title.color = style.getPropertyValue('--text-secondary').trim();
                });
                if (chart.options.plugins?.legend?.labels) {
                    chart.options.plugins.legend.labels.color = style.getPropertyValue('--text-primary').trim();
                }
                chart.update('none');
            });
        }
    },
    updateToggleButton(theme) {
        const btn = document.getElementById('theme-toggle');
        if (btn) {
            const icon = btn.querySelector('.toggle-icon');
            const text = btn.querySelector('.theme-toggle-text');
            if (icon) icon.innerHTML = theme === 'dark'
                ? '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>'
                : '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
            if (text) text.textContent = theme === 'dark' ? 'Light' : 'Dark';
        }
    }
};

const Sidebar = {
    render() {
        const wrapper = document.querySelector('.app-wrapper');
        if (!wrapper) return;
        
        // Prevent duplicate rendering
        if (wrapper.querySelector('.app-sidebar')) return;

        const sidebarHTML = `
        <aside class="app-sidebar">
            <button class="sidebar-toggle-btn" onclick="Sidebar.toggle()" title="사이드바 접기/펼치기">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M15 18l-6-6 6-6"/>
                </svg>
            </button>
            <div class="sidebar-brand" style="justify-content: center;">
                <h1 style="font-size: 1.1rem; letter-spacing: -0.5px;">EIBE SCM System</h1>
            </div>
            <nav class="sidebar-nav">
                <a href="/" class="nav-item"><span class="nav-icon"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg></span><span>요약</span></a>
                <a href="/inventory" class="nav-item"><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg></span><span>현재고</span></a>
                <a href="/expiry" class="nav-item"><span class="nav-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></span><span>기한</span></a>
                <a href="/order-plan" class="nav-item"><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></span><span>발주</span></a>
                <a href="/matching" class="nav-item"><span class="nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg></span><span>입고</span></a>
                <div class="nav-group">
                    <a href="/users" class="nav-parent"><span class="nav-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg></span><span>설정</span></a>
                    <div class="nav-sub">
                        <a href="/users#template-header">데이터 양식</a>
                        <a href="/users#warehouse-header">창고 관리</a>
                        <a href="/users#product-header">품목 관리</a>
                        <a href="/users#user-header">사용자 관리</a>
                        <a href="/users#snapshot-header">백업/스냅샷</a>
                        <a href="/users#moq-header">이관 MOQ</a>
                    </div>
                </div>
            </nav>
            <div class="sidebar-user-info">
                <div class="user-avatar" id="sidebar-user-avatar">U</div>
                <div class="user-meta">
                    <div class="user-name" id="sidebar-user-name">로딩 중...</div>
                    <div class="user-role" id="sidebar-user-role">-</div>
                </div>
            </div>
            <div class="sidebar-footer">
                <button id="theme-toggle" class="theme-toggle" onclick="Theme.toggle()">
                    <span class="toggle-icon"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg></span>
                    <span class="theme-toggle-text">Dark</span>
                </button>
                <button class="btn btn--secondary btn--sm" onclick="Auth.logout()" style="width:100%; text-align:center;">로그아웃</button>
            </div>
        </aside>
        `;
        
        wrapper.insertAdjacentHTML('afterbegin', sidebarHTML);
    },

    init() {
        this.render();
        const sidebar = document.querySelector('.app-sidebar');
        if (!sidebar) return;
        const collapsed = localStorage.getItem('sidebar_collapsed') === 'true';
        if (collapsed) sidebar.classList.add('collapsed');

        const currentPath = window.location.pathname;
        document.querySelectorAll('.nav-group').forEach(group => {
            const parentLink = group.querySelector('.nav-parent');
            const subLinks = group.querySelectorAll('.nav-sub a');
            
            let isActive = false;
            subLinks.forEach(link => {
                // Exact match or active logic
                if (link.getAttribute('href') === currentPath) {
                    link.classList.add('active');
                    isActive = true;
                }
            });

            if (isActive) {
                group.classList.add('expanded');
                if (parentLink) parentLink.classList.add('active');
            }

            if (parentLink) {
                parentLink.addEventListener('click', (e) => {
                    e.preventDefault();
                    group.classList.toggle('expanded');
                });
            }
        });
    },
    toggle() {
        const sidebar = document.querySelector('.app-sidebar');
        if (!sidebar) return;
        sidebar.classList.toggle('collapsed');
        localStorage.setItem('sidebar_collapsed', sidebar.classList.contains('collapsed'));
    }
};

const ChartDefaults = {
    init() {
        if (typeof Chart === 'undefined') return;
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        
        Chart.defaults.font.family = "'Inter', sans-serif";
        Chart.defaults.color = isDark ? '#a0a0a0' : '#8b95a1';
        Chart.defaults.elements.line.tension = 0.35;
        Chart.defaults.scale.grid = {
            color: isDark ? 'rgba(100, 100, 100, 0.15)' : '#e5e8eb',
            drawBorder: false,
        };
        Chart.defaults.plugins.tooltip.backgroundColor = isDark ? 'rgba(26, 26, 26, 0.95)' : 'rgba(255, 255, 255, 0.95)';
        Chart.defaults.plugins.tooltip.titleColor = isDark ? '#e8e8e8' : '#191f28';
        Chart.defaults.plugins.tooltip.bodyColor = isDark ? '#e8e8e8' : '#191f28';
    },

    createDualTrackChart(canvasId, labels, demandData, depletionData, salesData) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;

        const datasets = [
            {
                label: '예상 재고 추이',
                data: demandData,
                borderColor: '#29AD3A',
                backgroundColor: 'rgba(41, 173, 58, 0.06)',
                fill: true, borderWidth: 2,
            },
            {
                label: '재고 소멸선',
                data: depletionData,
                borderColor: '#e53535',
                backgroundColor: 'rgba(229, 53, 53, 0.04)',
                fill: true, borderWidth: 2, borderDash: [6, 3],
            },
        ];

        if (salesData && salesData.length) {
            datasets.push({
                label: '실제 판매량',
                data: salesData,
                type: 'bar',
                backgroundColor: 'rgba(41, 173, 58, 0.35)',
                borderRadius: 3,
                order: 2,
            });
        }

        return new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: { labels, datasets },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false } }
        });
    }
};

const Toast = {
    container: null,
    init() {
        this.container = document.getElementById('toast-container');
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.id = 'toast-container';
            this.container.className = 'toast-container';
            document.body.appendChild(this.container);
        }
    },
    show(message, type) {
        if (!this.container) this.init();
        const toast = document.createElement('div');
        toast.className = 'toast';
        if (type === 'error') toast.className += ' toast--error';
        else if (type === 'success') toast.className += ' toast--success';
        toast.textContent = message;
        this.container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(12px)';
            toast.style.transition = 'all 0.2s ease';
            setTimeout(() => toast.remove(), 200);
        }, 3000);
    }
};

/** Tabs helper */
function switchTab(tabGroupId, tabName) {
    const group = document.getElementById(tabGroupId);
    if (!group) return;
    group.querySelectorAll('.tab-nav button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    group.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `tab-${tabName}`);
    });
}

/** Excel template download helper */
function downloadTemplate(type) {
    const url = type === 'all' ? '/api/excel/template/all' : `/api/excel/template/${type}`;
    window.location.href = url;
}

/** Collapsible toggle */
function toggleCollapsible(headerId) {
    const header = document.getElementById(headerId);
    if (!header) return;
    const body = header.nextElementSibling;
    if (!body) return;
    header.classList.toggle('collapsed');
    body.classList.toggle('hidden');
}

/** Inject today's date into page header (right-aligned) */
function injectTodayDate() {
    const header = document.querySelector('.page-header');
    if (!header) return;
    const existing = header.querySelector('.page-date');
    if (existing) return;
    const dateEl = document.createElement('div');
    dateEl.className = 'page-date';
    dateEl.textContent = Format.today();
    header.appendChild(dateEl);
}

/** Display logged-in user info in sidebar footer */
async function loadSidebarUser() {
    const userArea = document.querySelector('.sidebar-user-info');
    if (!userArea) return;
    try {
        const user = await API.get('/api/auth/me');
        if (user) {
            userArea.querySelector('.user-name').textContent = user.name || user.username;
            userArea.querySelector('.user-role').textContent = user.role === 'ADMIN' ? '관리자' : '운영자';
        }
    } catch(e) {
        // Not logged in or API unavailable
    }
}

const TableSort = {
    init() {
        document.querySelectorAll('th[data-sort]').forEach(th => {
            th.classList.add('sortable');
            // Remove existing listeners by cloning (if any) to prevent duplicates
            const newTh = th.cloneNode(true);
            th.parentNode.replaceChild(newTh, th);
            newTh.addEventListener('click', () => this.sort(newTh));
        });
    },
    sort(th) {
        const table = th.closest('table');
        const tbody = table.querySelector('tbody');
        if (!tbody) return;
        const colIndex = Array.from(th.parentNode.children).indexOf(th);
        const type = th.dataset.sort;
        let isAsc = th.classList.contains('sort-asc');
        
        table.querySelectorAll('th').forEach(h => {
            h.classList.remove('sort-asc', 'sort-desc');
        });
        
        isAsc = !isAsc;
        th.classList.add(isAsc ? 'sort-asc' : 'sort-desc');

        const rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort((a, b) => {
            const aText = a.children[colIndex]?.textContent.trim() || '';
            const bText = b.children[colIndex]?.textContent.trim() || '';
            
            if (type === 'number') {
                const aNum = parseFloat(aText.replace(/[^0-9.-]+/g,"")) || 0;
                const bNum = parseFloat(bText.replace(/[^0-9.-]+/g,"")) || 0;
                return isAsc ? aNum - bNum : bNum - aNum;
            }
            return isAsc ? aText.localeCompare(bText) : bText.localeCompare(aText);
        });
        
        tbody.append(...rows);
    }
};

const BrandFilter = {
    async init(selectId, onChange) {
        const selectElem = document.getElementById(selectId);
        if (!selectElem) return;

        try {
            const products = await API.get('/api/products');
            const brands = new Set();
            products.forEach(p => {
                if (p.brand_category) brands.add(p.brand_category);
            });
            
            const brandList = Array.from(brands).sort();
            selectElem.innerHTML = `<option value="ALL">전체 브랜드</option>` + 
                                   brandList.map(b => `<option value="${b}">${b}</option>`).join('');
            
            selectElem.addEventListener('change', (e) => {
                if (onChange) onChange(e.target.value);
            });
        } catch(e) {
            console.error('Failed to load brands for filter', e);
        }
    }
};

const FilterUI = {
    init(containerId, options, onChange) {
        const container = document.getElementById(containerId);
        if (!container) return;

        let selected = [...options]; // default select all

        container.innerHTML = `
            <div class="custom-filter">
                <button class="filter-dropdown-btn">
                    <span class="filter-label">필터: 전체 선택됨</span>
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                </button>
                <div class="filter-dropdown-menu hidden">
                    <div class="filter-menu-header">
                        <button class="btn btn--secondary btn--sm" id="btn-select-all-${containerId}">전체 선택</button>
                        <button class="btn btn--secondary btn--sm" id="btn-clear-all-${containerId}">선택 해제</button>
                    </div>
                    <div class="filter-options">
                        ${options.map(opt => `
                            <label class="filter-option-label">
                                <input type="checkbox" value="${opt}" checked>
                                <span>${opt}</span>
                            </label>
                        `).join('')}
                    </div>
                </div>
            </div>
            <div class="filter-chips">
                ${options.map(opt => `
                    <div class="filter-chip" data-value="${opt}">
                        ${opt}
                        <span class="chip-remove">×</span>
                    </div>
                `).join('')}
            </div>
        `;

        const btn = container.querySelector('.filter-dropdown-btn');
        const menu = container.querySelector('.filter-dropdown-menu');
        const checkboxes = container.querySelectorAll('.filter-options input[type="checkbox"]');
        const btnAll = container.querySelector(`#btn-select-all-${containerId}`);
        const btnClear = container.querySelector(`#btn-clear-all-${containerId}`);
        const chipsContainer = container.querySelector('.filter-chips');

        // Toggle dropdown
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.toggle('hidden');
        });
        document.addEventListener('click', (e) => {
            if (!container.contains(e.target)) menu.classList.add('hidden');
        });

        // Update UI
        const updateUI = () => {
            selected = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);
            
            // Update button label
            const label = container.querySelector('.filter-label');
            if (selected.length === options.length) label.textContent = '필터: 전체 선택됨';
            else if (selected.length === 0) label.textContent = '필터: 선택 없음';
            else label.textContent = `필터: ${selected.length}개 선택됨`;

            // Update chips
            chipsContainer.innerHTML = selected.map(opt => `
                <div class="filter-chip" data-value="${opt}">
                    ${opt}
                    <span class="chip-remove">×</span>
                </div>
            `).join('');

            // Re-bind chip remove
            chipsContainer.querySelectorAll('.chip-remove').forEach(rmBtn => {
                rmBtn.addEventListener('click', (e) => {
                    const val = e.target.closest('.filter-chip').dataset.value;
                    const cb = Array.from(checkboxes).find(c => c.value === val);
                    if (cb) { cb.checked = false; updateUI(); }
                });
            });

            if (onChange) onChange(selected);
        };

        checkboxes.forEach(cb => cb.addEventListener('change', updateUI));
        btnAll.addEventListener('click', () => { checkboxes.forEach(cb => cb.checked = true); updateUI(); });
        btnClear.addEventListener('click', () => { checkboxes.forEach(cb => cb.checked = false); updateUI(); });
    }
};

document.addEventListener('DOMContentLoaded', () => {
    Theme.init();
    Toast.init();
    TableSort.init();
    injectTodayDate();
    if (typeof Chart !== 'undefined') ChartDefaults.init();
    // Auth check (skip for login page)
    if (!window.location.pathname.startsWith('/login')) {
        Auth.init();
        loadSidebarUser();
    }
});

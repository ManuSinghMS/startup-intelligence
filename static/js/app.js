/**
 * Startup Intelligence Platform — Frontend Application
 */

const API = '';
let currentFilters = {
    source_type: '',
    classification: '',
    date_from: '',
    keyword: '',
    offset: 0,
    limit: 50
};
let currentView = 'dashboard';
let companyTagFilter = '';
let analyticsCharts = {};

// ========== THEME ==========

function initTheme() {
    const saved = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    updateThemeIcon(saved);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeIcon(next);
}

function updateThemeIcon(theme) {
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = theme === 'dark' ? '' : '';
}

initTheme();

// ========== INITIALIZATION ==========

document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
    setupEventListeners();
});

function setupEventListeners() {
    const searchInput = document.getElementById('search-input');
    let searchTimer;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            currentFilters.keyword = e.target.value;
            currentFilters.offset = 0;
            loadContent();
        }, 400);
    });

    const companySearch = document.getElementById('company-search');
    if (companySearch) {
        let companyTimer;
        companySearch.addEventListener('input', (e) => {
            clearTimeout(companyTimer);
            companyTimer = setTimeout(() => loadCompanies(e.target.value), 400);
        });
    }

    document.querySelectorAll('.filter-btn[data-filter]').forEach(btn => {
        btn.addEventListener('click', () => {
            const filterType = btn.dataset.filter;
            const value = btn.dataset.value;

            btn.closest('.filter-group').querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            if (filterType === 'source_type') {
                currentFilters.source_type = value;
            } else if (filterType === 'classification') {
                currentFilters.classification = value;
            } else if (filterType === 'date') {
                if (value) {
                    const d = new Date();
                    d.setDate(d.getDate() - parseInt(value));
                    currentFilters.date_from = d.toISOString();
                } else {
                    currentFilters.date_from = '';
                }
            }

            currentFilters.offset = 0;
            loadContent();
        });
    });
}

// ========== VIEW MANAGEMENT ==========

function showView(view) {
    currentView = view;
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    const navBtn = document.getElementById(`nav-${view}`);
    if (navBtn) navBtn.classList.add('active');

    document.querySelectorAll('[id^="view-"]').forEach(v => v.style.display = 'none');
    const viewEl = document.getElementById(`view-${view}`);
    if (viewEl) viewEl.style.display = 'block';

    // Show sidebar only on dashboard
    const sidebar = document.getElementById('sidebar');
    sidebar.style.display = (view === 'dashboard') ? '' : 'none';
    document.querySelector('.main').style.gridTemplateColumns = (view === 'dashboard') ? '280px 1fr' : '1fr';

    switch (view) {
        case 'dashboard': loadDashboard(); break;
        case 'analytics': loadAnalytics(); break;
        case 'companies': loadCompanies(); break;
        case 'digest': loadDigest(); break;
        case 'sources': loadSources(); break;
    }
}

// ========== DASHBOARD ==========

async function loadDashboard() {
    await Promise.all([loadStats(), loadContent()]);
}

async function loadStats() {
    try {
        const res = await fetch(`${API}/api/health`);
        const data = await res.json();
        document.getElementById('stat-startups').textContent = data.counts.startups;
        document.getElementById('stat-content').textContent = data.counts.content_items;
        document.getElementById('stat-sources').textContent = data.counts.sources;
        document.getElementById('stat-summaries').textContent = data.counts.summaries;
    } catch (e) {
        console.error('Failed to load stats:', e);
    }
}

async function loadContent() {
    const feed = document.getElementById('content-feed');
    feed.innerHTML = '<div class="loading"><div class="spinner"></div><span>Loading content...</span></div>';

    const params = new URLSearchParams();
    if (currentFilters.source_type) params.set('source_type', currentFilters.source_type);
    if (currentFilters.classification) params.set('classification', currentFilters.classification);
    if (currentFilters.date_from) params.set('date_from', currentFilters.date_from);
    if (currentFilters.keyword) params.set('keyword', currentFilters.keyword);
    params.set('limit', 200);
    params.set('offset', 0);

    try {
        const res = await fetch(`${API}/api/content?${params}`);
        const data = await res.json();

        if (data.items.length === 0) {
            feed.innerHTML = `
 <div class="empty-state">
 <div class="icon"></div>
 <h3>No content found</h3>
 <p>Try adjusting your filters or run an ingestion to fetch new content.</p>
 </div>`;
            document.getElementById('pagination').innerHTML = '';
            return;
        }

        const grouped = {};
        const unmapped = [];
        data.items.forEach(item => {
            if (item.startup_name && item.startup_id) {
                if (!grouped[item.startup_id]) {
                    grouped[item.startup_id] = { name: item.startup_name, id: item.startup_id, items: [] };
                }
                grouped[item.startup_id].items.push(item);
            } else {
                unmapped.push(item);
            }
        });

        const companies = Object.values(grouped).sort((a, b) => b.items.length - a.items.length);

        let html = '';
        for (const company of companies) {
            html += renderCompanyGroup(company);
        }

        if (unmapped.length > 0) {
            html += `
 <div style="margin-top: 1.5rem;">
 <div class="section-header">
 <h3 class="section-title" style="font-size: 1rem; color: var(--text-muted);">Unmatched Items (${unmapped.length})</h3>
 </div>
                    ${unmapped.map(item => renderContentCard(item)).join('')}
 </div>`;
        }

        feed.innerHTML = html;
        updateFilterCounts();
        document.getElementById('feed-subtitle').textContent =
            `${data.total} items across ${companies.length} companies${currentFilters.keyword ? ` matching "${currentFilters.keyword}"` : ''}`;
        document.getElementById('pagination').innerHTML = '';
    } catch (e) {
        feed.innerHTML = `
 <div class="empty-state">
 <div class="icon"></div>
 <h3>Failed to load content</h3>
 <p>Make sure the server is running at ${API || 'localhost:8000'}</p>
 </div>`;
    }
}

function renderCompanyGroup(company) {
    const latestItems = company.items.slice(0, 5);
    const hasMore = company.items.length > 5;

    return `
 <div style="margin-bottom: 2rem;" class="company-group" data-company-id="${company.id}">
 <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
 <a href="/company/${company.id}" style="display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--text-primary);">
 <div style="width: 36px; height: 36px; border-radius: 8px; background: linear-gradient(135deg, var(--accent), var(--funding)); display: flex; align-items: center; justify-content: center; font-size: 0.8rem; font-weight: 700; color: white; flex-shrink: 0;">
                        ${company.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
 </div>
 <div>
 <div style="font-weight: 600; font-size: 1rem;">${company.name}</div>
 <div style="font-size: 0.75rem; color: var(--text-muted);" class="article-count-text">${company.items.length} article${company.items.length !== 1 ? 's' : ''} found</div>
 </div>
 </a>
                ${hasMore ? `<a href="/company/${company.id}" class="nav-btn view-all-text" style="font-size: 0.75rem; text-decoration: none;">View all ${company.items.length} →</a>` : ''}
 </div>
 <div class="content-feed">
                ${latestItems.map(item => renderContentCard(item)).join('')}
 </div>
 </div>`;
}

function renderContentCard(item) {
    const date = item.published_at ? new Date(item.published_at).toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric'
    }) : 'Unknown date';

    const classLabel = {
        funding: ' Funding', product_launch: ' Product', milestone: ' Milestone',
        hiring: ' Hired', partnership: ' Partnership', customer_win: ' Customer',
        general: ' General', unclassified: ' Unclassified'
    };
    const urlKindLabel = {
        founder_post_url:        ' Founder LinkedIn post',
        cofounder_post_url:      ' Co-founder LinkedIn post',
        company_post_url:        ' Company LinkedIn post',
        founder_activity_page:   ' Founder activity page',
        cofounder_activity_page: ' Co-founder activity page',
        company_activity_page:   ' Company activity page',
        founder_profile_url:     ' Founder LinkedIn profile',
        cofounder_profile_url:   ' Co-founder LinkedIn profile',
        company_page_url:        ' Company LinkedIn page',
        news_mention:            ' News mention',
        web_mention:             ' Web mention',
    };

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    if (item.ingestion_status === 'url_only') {
        const kind = urlKindLabel[item.classification] || 'LinkedIn link';
        const isPost = (item.classification || '').endsWith('_post_url');
        const ctaLabel = isPost ? ' Open LinkedIn Post'
                        : (item.classification || '').endsWith('_activity_page') ? ' Open Activity Page'
                        : ' Open Link';
        const sourceLabel = item.external_source === 'manual' ? 'Manual / Monday'
                          : item.external_source === 'google_news_rss' ? 'Auto (Google News)'
                          : (item.source_name || 'LinkedIn');
        return `
 <div class="content-card" data-id="${item.id}" style="border-left:4px solid #0a66c2;">
 <div class="content-card-header">
 <div class="content-card-title">
                    ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener" style="color:#0a66c2;">${escapeHtml(item.title || 'LinkedIn link')}</a>` : escapeHtml(item.title || 'Untitled')}
 </div>
 <div style="display:flex;gap:6px;align-items:center;">
 <span class="tag" style="background:#e8f0fe;color:#0a66c2;">${kind}</span>
 <button onclick="deleteContent('${item.id}', this)" title="Delete this item"
                        style="background:none;border:none;cursor:pointer;font-size:0.85rem;padding:2px 4px;border-radius:4px;opacity:0.5;"
                        onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.5'"></button>
 </div>
 </div>
            ${item.url ? `<div style="margin-top:8px;"><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener" class="btn btn-primary" style="background:#0a66c2;color:white;text-decoration:none;padding:6px 12px;border-radius:4px;font-weight:500;display:inline-block;font-size:13px;">${ctaLabel}</a></div>` : ''}
 <div class="content-card-meta" style="margin-top:8px;">
                ${item.startup_name ? `<a href="/company/${item.startup_id}" class="startup-tag">${escapeHtml(item.startup_name)}</a>` : ''}
 <span class="meta-item"><span class="icon"></span> ${escapeHtml(sourceLabel)}</span>
                ${item.author_name ? `<span class="meta-item"><span class="icon"></span> ${escapeHtml(item.author_name)}</span>` : ''}
 <span class="meta-item"><span class="icon"></span> ${date}</span>
 </div>
 </div>`;
    }

    const urlLink = item.url ? `<a href="${item.url}" target="_blank" rel="noopener">${item.title || 'Untitled'}</a>` : (item.title || 'Untitled');

    return `
 <div class="content-card" data-id="${item.id}">
 <div class="content-card-header">
 <div class="content-card-title">${urlLink}</div>
 <div style="display:flex;gap:6px;align-items:center;">
 <span class="tag tag-${item.classification || 'unclassified'}">
                        ${classLabel[item.classification] || item.classification || 'Unclassified'}
 </span>
 <button onclick="deleteContent('${item.id}', this)" title="Delete this item"
                        style="background:none;border:none;cursor:pointer;font-size:0.85rem;padding:2px 4px;border-radius:4px;opacity:0.5;transition:opacity 0.2s;"
                        onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.5'"></button>
 </div>
 </div>
            ${item.summary ? `<div class="content-card-summary">${item.summary}</div>` : ''}
 <div class="content-card-meta">
                ${item.startup_name ? `<a href="/company/${item.startup_id}" class="startup-tag">${item.startup_name}</a>` : ''}
 <span class="meta-item"><span class="icon"></span> ${item.source_name || 'Unknown'}</span>
 <span class="meta-item"><span class="icon"></span> ${date}</span>
 <span class="tag tag-${item.source_type}">${item.source_type}</span>
                ${item.sentiment ? `<span class="meta-item">${item.sentiment === 'positive' ? '' : item.sentiment === 'negative' ? '' : ''} ${item.sentiment}</span>` : ''}
 </div>
 </div>`;
}

function renderPagination(total) {
    const container = document.getElementById('pagination');
    const pages = Math.ceil(total / currentFilters.limit);
    const currentPage = Math.floor(currentFilters.offset / currentFilters.limit) + 1;

    if (pages <= 1) { container.innerHTML = ''; return; }

    let html = `<button class="page-btn" onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>← Prev</button>`;
    const start = Math.max(1, currentPage - 2);
    const end = Math.min(pages, currentPage + 2);
    for (let i = start; i <= end; i++) {
        html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }
    html += `<button class="page-btn" onclick="goToPage(${currentPage + 1})" ${currentPage === pages ? 'disabled' : ''}>Next →</button>`;
    container.innerHTML = html;
}

function goToPage(page) {
    currentFilters.offset = (page - 1) * currentFilters.limit;
    loadContent();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function updateFilterCounts() {
    try {
        const res = await fetch(`${API}/api/content/stats/overview`);
        const data = await res.json();

        if (data.by_source_type) {
            Object.entries(data.by_source_type).forEach(([type, count]) => {
                const el = document.getElementById(`count-${type}`);
                if (el) el.textContent = count;
            });
        }
        if (data.by_classification) {
            Object.entries(data.by_classification).forEach(([cls, count]) => {
                const el = document.getElementById(`count-${cls}`);
                if (el) el.textContent = count;
            });
        }
    } catch (e) {
        console.error('Failed to load filter counts:', e);
    }
}

// ========== ANALYTICS ==========

const CHART_COLORS = {
    funding: '#f59e0b',
    product_launch: '#3b82f6',
    milestone: '#10b981',
    hiring: '#22c55e',
    partnership: '#8b5cf6',
    customer_win: '#ec4899',
    general: '#6b7280',
    unclassified: '#9ca3af',
    news: '#3b82f6',
    newsletter: '#f59e0b',
    social: '#8b5cf6',
    press: '#ef4444',
    blog: '#10b981',
    positive: '#22c55e',
    neutral: '#6b7280',
    negative: '#ef4444',
};

const CHART_LABELS = {
    funding: ' Funding',
    product_launch: ' Product Launch',
    milestone: ' Milestone',
    hiring: ' Hired',
    partnership: ' Partnership',
    customer_win: ' Customer Win',
    general: ' General',
    unclassified: ' Unclassified',
};

async function loadAnalytics() {
    try {
        const res = await fetch(`${API}/api/analytics`);
        const data = await res.json();

        // KPIs
        document.getElementById('kpi-hiring').textContent = data.kpis.hiring;
        document.getElementById('kpi-funding').textContent = data.kpis.funding;
        document.getElementById('kpi-partnerships').textContent = data.kpis.partnerships;
        document.getElementById('kpi-products').textContent = data.kpis.products;

        // Destroy existing charts
        Object.values(analyticsCharts).forEach(c => c.destroy());
        analyticsCharts = {};

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const textColor = isDark ? '#e2e8f0' : '#374151';
        const gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';

        Chart.defaults.color = textColor;
        Chart.defaults.borderColor = gridColor;

        // Category Pie
        const catEntries = Object.entries(data.by_classification).filter(([k]) => k);
        analyticsCharts.category = new Chart(document.getElementById('chart-category'), {
            type: 'doughnut',
            data: {
                labels: catEntries.map(([k]) => CHART_LABELS[k] || k),
                datasets: [{
                    data: catEntries.map(([, v]) => v),
                    backgroundColor: catEntries.map(([k]) => CHART_COLORS[k] || '#6b7280'),
                    borderWidth: 2,
                    borderColor: isDark ? '#1e293b' : '#ffffff',
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right', labels: { padding: 12, usePointStyle: true, font: { size: 11 } } }
                }
            }
        });

        // Source Type Pie
        const srcEntries = Object.entries(data.by_source_type).filter(([k]) => k);
        analyticsCharts.sourceType = new Chart(document.getElementById('chart-source-type'), {
            type: 'doughnut',
            data: {
                labels: srcEntries.map(([k]) => k.charAt(0).toUpperCase() + k.slice(1)),
                datasets: [{
                    data: srcEntries.map(([, v]) => v),
                    backgroundColor: srcEntries.map(([k]) => CHART_COLORS[k] || '#6b7280'),
                    borderWidth: 2,
                    borderColor: isDark ? '#1e293b' : '#ffffff',
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right', labels: { padding: 12, usePointStyle: true, font: { size: 11 } } }
                }
            }
        });

        // Sentiment Bar
        const sentEntries = Object.entries(data.by_sentiment).filter(([k]) => k);
        analyticsCharts.sentiment = new Chart(document.getElementById('chart-sentiment'), {
            type: 'bar',
            data: {
                labels: sentEntries.map(([k]) => k.charAt(0).toUpperCase() + k.slice(1)),
                datasets: [{
                    label: 'Content Items',
                    data: sentEntries.map(([, v]) => v),
                    backgroundColor: sentEntries.map(([k]) => CHART_COLORS[k] || '#6b7280'),
                    borderRadius: 6,
                    barThickness: 40,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, grid: { color: gridColor } },
                    x: { grid: { display: false } }
                }
            }
        });

        // Top Companies Horizontal Bar
        analyticsCharts.topCompanies = new Chart(document.getElementById('chart-top-companies'), {
            type: 'bar',
            data: {
                labels: data.top_companies.map(c => c.name.length > 20 ? c.name.slice(0, 20) + '…' : c.name),
                datasets: [{
                    label: 'Content Items',
                    data: data.top_companies.map(c => c.count),
                    backgroundColor: 'rgba(59, 130, 246, 0.7)',
                    borderRadius: 4,
                    barThickness: 18,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: { legend: { display: false } },
                scales: {
                    x: { beginAtZero: true, grid: { color: gridColor } },
                    y: { grid: { display: false } }
                }
            }
        });

        // Timeline Line Chart
        analyticsCharts.timeline = new Chart(document.getElementById('chart-timeline'), {
            type: 'line',
            data: {
                labels: data.content_timeline.map(d => {
                    const dt = new Date(d.date);
                    return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                }),
                datasets: [{
                    label: 'Content Items',
                    data: data.content_timeline.map(d => d.count),
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 3,
                    pointHoverRadius: 6,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, grid: { color: gridColor } },
                    x: { grid: { display: false } }
                }
            }
        });

        // Drilldowns
        renderDrilldown('drilldown-hiring', data.category_by_company.hiring || []);
        renderDrilldown('drilldown-funding', data.category_by_company.funding || []);

    } catch (e) {
        console.error('Failed to load analytics:', e);
    }
}

function renderDrilldown(containerId, items) {
    const container = document.getElementById(containerId);
    if (!items.length) {
        container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem; padding: 0.5rem;">No data yet — run ingestion and classification first.</div>';
        return;
    }
    container.innerHTML = items.map((item, i) => `
 <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid var(--border);">
 <span style="font-size: 0.85rem;">${i + 1}. ${item.name}</span>
 <span style="font-size: 0.85rem; font-weight: 600; color: var(--accent);">${item.count}</span>
 </div>
    `).join('');
}

async function reclassifyAll() {
    const btn = document.getElementById('btn-reclassify');
    btn.textContent = '⏳ Classifying...';
    btn.disabled = true;
    try {
        const res = await fetch(`${API}/api/reclassify`, { method: 'POST' });
        const data = await res.json();
        showToast(`Re-classified ${data.reclassified} items (${data.errors} errors)`, 'success');
        loadAnalytics();
    } catch (e) {
        showToast('Re-classification failed', 'error');
    } finally {
        btn.textContent = ' Re-classify All';
        btn.disabled = false;
    }
}

// ========== COMPANIES ==========

function buildTagFilterBar() {
    return `
 <div style="display:flex;gap:8px;margin-bottom:1rem;flex-wrap:wrap;align-items:center;">
 <span style="font-size:0.8rem;color:var(--text-muted);font-weight:600;">Filter:</span>
 <button class="nav-btn ${!companyTagFilter ? 'active' : ''}" onclick="setTagFilter('')" style="font-size:0.75rem;">All Active</button>
 <button class="nav-btn ${companyTagFilter === 'active' ? 'active' : ''}" onclick="setTagFilter('active')" style="font-size:0.75rem;">Active</button>
 <button class="nav-btn ${companyTagFilter === 'alumni' ? 'active' : ''}" onclick="setTagFilter('alumni')" style="font-size:0.75rem;">Alumni</button>
 <button class="nav-btn ${companyTagFilter === 'not_active' ? 'active' : ''}" onclick="setTagFilter('not_active')" style="font-size:0.75rem;">Not Active</button>
 <button class="nav-btn ${companyTagFilter === 'all' ? 'active' : ''}" onclick="setTagFilter('all')" style="font-size:0.75rem;">Show All</button>
 <span style="flex:1;"></span>
 <button class="nav-btn" onclick="removeDeactivated()" style="font-size:0.75rem;color:var(--danger);"
                title="Permanently delete all not_active companies">Remove Deactivated</button>
 </div>`;
}

async function loadCompanies(search = '') {
    const container = document.getElementById('companies-list');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><span>Loading companies...</span></div>';

    try {
        const params = new URLSearchParams();
        if (search) params.set('search', search);
        if (companyTagFilter && companyTagFilter !== 'all') params.set('tag', companyTagFilter);
        if (companyTagFilter === 'all') params.set('include_inactive', 'true');

        const res = await fetch(`${API}/api/startups?${params}`);
        const data = await res.json();

        const filterBar = buildTagFilterBar();

        if (data.startups.length === 0) {
            container.innerHTML = filterBar + '<div class="empty-state"><div class="icon"></div><h3>No companies with this tag</h3><p>Try a different filter above.</p></div>';
            return;
        }

        const tagBadge = (tag) => {
            const badges = {
                active: '<span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:0.65rem;font-weight:600;background:#22c55e20;color:#22c55e;">Active</span>',
                alumni: '<span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:0.65rem;font-weight:600;background:#3b82f620;color:#3b82f6;">Alumni</span>',
                not_active: '<span style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:0.65rem;font-weight:600;background:#ef444420;color:#ef4444;">Not Active</span>',
            };
            return badges[tag] || badges.active;
        };

        container.innerHTML = filterBar + data.startups.map(s => `
 <div class="content-card" style="position:relative;">
 <div class="content-card-header">
 <div>
 <a href="/company/${s.id}" style="text-decoration:none;color:var(--text-primary);">
 <div class="content-card-title">
                                ${s.name}
                                ${tagBadge(s.tag || 'active')}
 </div>
 </a>
                        ${s.legal_name ? `<div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 2px;">${s.legal_name}</div>` : ''}
 </div>
 <div style="display:flex;gap:6px;align-items:center;">
 <span class="tag tag-general">${s.content_count || 0} items</span>
 <select onchange="changeTag('${s.id}', this.value)" style="font-size:0.7rem;padding:2px 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--text-primary);cursor:pointer;">
 <option value="active" ${(s.tag || 'active') === 'active' ? 'selected' : ''}>Active</option>
 <option value="alumni" ${s.tag === 'alumni' ? 'selected' : ''}>Alumni</option>
 <option value="not_active" ${s.tag === 'not_active' ? 'selected' : ''}>Not Active</option>
 </select>
 </div>
 </div>
 <div class="content-card-meta">
                    ${s.industry ? `<span class="meta-item"> ${s.industry}</span>` : ''}
                    ${s.stage ? `<span class="meta-item"> ${s.stage}</span>` : ''}
                    ${s.contact_name ? `<span class="meta-item"> ${s.contact_name}</span>` : ''}
                    ${s.last_activity ? `<span class="meta-item">Last: ${new Date(s.last_activity).toLocaleDateString()}</span>` : ''}
                    ${s.linkedin_url ? `<a href="${s.linkedin_url}" target="_blank" class="meta-item" style="text-decoration:none;">LinkedIn</a>` : ''}
 </div>
 </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<div class="empty-state"><div class="icon"></div><h3>Failed to load companies</h3></div>';
    }
}

function setTagFilter(tag) {
    companyTagFilter = tag;
    loadCompanies(document.getElementById('company-search')?.value || '');
}

async function changeTag(startupId, newTag) {
    try {
        const res = await fetch(`${API}/api/startups/${startupId}/tag?tag=${newTag}`, { method: 'PATCH' });
        if (res.ok) {
            showToast(`Tag updated to ${newTag}`, 'success');
        } else {
            showToast('Failed to update tag', 'error');
        }
    } catch (e) {
        showToast('Failed to update tag', 'error');
    }
}

async function removeDeactivated() {
    if (!confirm('This will PERMANENTLY delete all companies tagged as "Not Active" and their content. Continue?')) return;

    try {
        const res = await fetch(`${API}/api/startups/deactivated`, { method: 'DELETE' });
        const data = await res.json();
        if (data.deleted > 0) {
            showToast(`Removed ${data.deleted} deactivated companies: ${data.companies.join(', ')}`, 'success');
        } else {
            showToast('No deactivated companies to remove', 'info');
        }
        loadCompanies();
    } catch (e) {
        showToast('Failed to remove deactivated companies', 'error');
    }
}

// ========== CSV IMPORT ==========

function showImportModal() {
    document.getElementById('modal-import').classList.add('active');
    document.getElementById('import-result').style.display = 'none';
    document.getElementById('import-file').value = '';
}

async function submitImport() {
    const fileInput = document.getElementById('import-file');
    if (!fileInput.files.length) {
        showToast('Please select a file first', 'error');
        return;
    }

    const btn = document.getElementById('btn-import');
    btn.textContent = '⏳ Importing...';
    btn.disabled = true;

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        const res = await fetch(`${API}/api/startups/import`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();

        if (res.ok) {
            const resultEl = document.getElementById('import-result');
            resultEl.style.display = 'block';
            resultEl.innerHTML = `
 <div style="font-size: 0.9rem;">
 <div style="color: var(--success); font-weight: 600; margin-bottom: 0.5rem;">Import Complete</div>
 <div> <strong>${data.imported}</strong>new companies imported</div>
 <div>⏭ <strong>${data.skipped}</strong>duplicates skipped</div>
 <div> <strong>${data.total_in_file}</strong>total rows in file</div>
 </div>`;
            showToast(`Imported ${data.imported} companies (${data.skipped} skipped)`, 'success');
            loadCompanies();
        } else {
            showToast(data.detail || 'Import failed', 'error');
        }
    } catch (e) {
        showToast('Import failed — check file format', 'error');
    } finally {
        btn.textContent = ' Upload & Import';
        btn.disabled = false;
    }
}

async function syncFromMonday() {
    const btn = document.getElementById('btn-sync-monday');
    const originalText = btn.textContent;
    btn.textContent = '⏳ Syncing...';
    btn.disabled = true;

    try {
        const res = await fetch(`${API}/api/startups/sync-monday`, {
            method: 'POST',
        });
        const data = await res.json();

        if (res.ok && data.status === 'completed') {
            const msg = `Synced ${data.created} new + ${data.updated} updated (${data.skipped} skipped)`;
            showToast(msg, 'success');
            loadCompanies();
        } else if (data.status === 'not_configured') {
            showToast('Monday.com not configured — set MONDAY_API_TOKEN and MONDAY_BOARD_ID in .env', 'error');
        } else {
            showToast(data.message || 'Sync failed', 'error');
        }
    } catch (e) {
        showToast('Sync failed — check server logs', 'error');
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

// ========== INGESTION MODAL ==========

let allCompaniesCache = [];

function showIngestionModal() {
    document.getElementById('modal-ingestion').classList.add('active');
    document.getElementById('company-picker').style.display = 'none';
    document.getElementById('ingestion-progress').style.display = 'none';
    loadCompaniesForPicker();
    refreshCycleSummary();
    pollIngestionStatus(true);
}

async function refreshCycleSummary() {
    try {
        const res = await fetch(`${API}/api/ingest/status`);
        const data = await res.json();
        const el = document.getElementById('cycle-summary');
        if (!el) return;
        el.textContent =
            `Cycle so far: ${data.cycled_24h} of ${data.total_companies} companies ingested in the last 24h ` +
            `(${data.remaining_24h} remaining).`;
    } catch (e) { /* non-fatal */ }
}

async function loadCompaniesForPicker() {
    try {
        const res = await fetch(`${API}/api/startups?limit=500`);
        const data = await res.json();
        allCompaniesCache = data.startups;
        renderCompanyPicker(allCompaniesCache);

        // Setup search filter
        const searchInput = document.getElementById('picker-search');
        searchInput.value = '';
        searchInput.oninput = () => {
            const q = searchInput.value.toLowerCase();
            renderCompanyPicker(allCompaniesCache.filter(s => s.name.toLowerCase().includes(q)));
        };
    } catch (e) {
        console.error('Failed to load companies for picker:', e);
    }
}

function renderCompanyPicker(companies) {
    const container = document.getElementById('company-checklist');
    container.innerHTML = companies.map(s => `
 <label style="display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; transition: background 0.15s;"
               onmouseover="this.style.background='var(--bg-sidebar)'" onmouseout="this.style.background='transparent'">
 <input type="checkbox" class="company-checkbox" value="${s.id}" style="cursor: pointer;">
 <span>${s.name}</span>
 <span style="margin-left: auto; font-size: 0.7rem; color: var(--text-muted);">${s.content_count || 0} items</span>
 </label>
    `).join('');

    // Update count on change
    container.querySelectorAll('.company-checkbox').forEach(cb => {
        cb.onchange = updatePickerCount;
    });
    updatePickerCount();
}

function updatePickerCount() {
    const checked = document.querySelectorAll('.company-checkbox:checked').length;
    document.getElementById('picker-count').textContent = `${checked} selected`;
}

function toggleCompanyPicker() {
    const picker = document.getElementById('company-picker');
    picker.style.display = picker.style.display === 'none' ? 'block' : 'none';
}

function toggleAllPicker() {
    const checkboxes = document.querySelectorAll('.company-checkbox');
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);
    checkboxes.forEach(cb => cb.checked = !allChecked);
    updatePickerCount();
}

let _ingestPollHandle = null;

async function runIngestion(mode) {
    const progress = document.getElementById('ingestion-progress');
    progress.style.display = 'block';
    const statusEl = document.getElementById('ingestion-status');
    document.getElementById('ingestion-bar').style.width = '0%';
    document.getElementById('ingestion-meta').textContent = '';
    document.getElementById('ingestion-current').textContent = '';
    statusEl.textContent = 'Starting...';

    let body = {};
    if (mode === 'selected') {
        const selected = Array.from(document.querySelectorAll('.company-checkbox:checked')).map(cb => cb.value);
        if (selected.length === 0) {
            showToast('Please select at least one company', 'error');
            progress.style.display = 'none';
            return;
        }
        body = { startup_ids: selected };
    }

    try {
        const res = await fetch(`${API}/api/ingest`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.status === 'already_running') {
            showToast('An ingestion job is already running. Showing live progress.', 'info');
        } else if (data.status === 'started') {
            showToast('Ingestion started in the background.', 'success');
        }
        pollIngestionStatus(false);
    } catch (e) {
        statusEl.textContent = 'Ingestion failed to start - check server logs.';
        showToast('Ingestion failed to start', 'error');
    }
}

function _stopIngestPolling() {
    if (_ingestPollHandle) {
        clearInterval(_ingestPollHandle);
        _ingestPollHandle = null;
    }
}

async function pollIngestionStatus(silentIfIdle) {
    _stopIngestPolling();
    const tick = async () => {
        let data;
        try {
            const res = await fetch(`${API}/api/ingest/status`);
            data = await res.json();
        } catch (e) {
            return;
        }
        const job = data.job || {};
        const progressBox = document.getElementById('ingestion-progress');
        const statusEl = document.getElementById('ingestion-status');
        const barEl = document.getElementById('ingestion-bar');
        const metaEl = document.getElementById('ingestion-meta');
        const currentEl = document.getElementById('ingestion-current');

        if (job.status === 'running') {
            progressBox.style.display = 'block';
            const total = job.total || 0;
            const done = job.completed || 0;
            const pct = total > 0 ? Math.round((done / total) * 100) : 5;
            statusEl.textContent = `Ingesting... ${done}/${total} companies (${pct}%)`;
            barEl.style.width = pct + '%';
            metaEl.textContent = `New items so far: ${job.new_items || 0} - Classified: ${job.classified || 0}`;
            currentEl.textContent = job.current_company ? `Currently processing: ${job.current_company}` : '';
            renderProcessedList(job.processed || []);
            refreshIngestionLogs();
        } else if (job.status === 'completed') {
            progressBox.style.display = 'block';
            statusEl.textContent = `Done. ${job.completed}/${job.total} companies, ${job.new_items} new items, ${job.classified} classified.`;
            barEl.style.width = '100%';
            currentEl.textContent = '';
            metaEl.textContent = `Cycle so far: ${data.cycled_24h} of ${data.total_companies} in the last 24h.`;
            renderProcessedList(job.processed || []);
            refreshCycleSummary();
            loadDashboard();
            refreshIngestionLogs();
            _stopIngestPolling();
        } else if (job.status === 'error') {
            progressBox.style.display = 'block';
            statusEl.textContent = `Error: ${job.error}`;
            renderProcessedList(job.processed || []);
            refreshIngestionLogs();
            _stopIngestPolling();
        } else {
            if (!silentIfIdle) {
                statusEl.textContent = 'No ingestion job running.';
            }
            _stopIngestPolling();
        }
    };
    await tick();
    _ingestPollHandle = setInterval(tick, 2500);
}

function _escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderProcessedList(processed) {
    const listEl = document.getElementById('ingestion-processed-list');
    const countEl = document.getElementById('ingestion-processed-count');
    if (!listEl) return;
    if (!processed || processed.length === 0) {
        listEl.innerHTML = '<span style="color: var(--text-muted);">None yet.</span>';
        if (countEl) countEl.textContent = '';
        return;
    }
    if (countEl) countEl.textContent = `(${processed.length})`;
    // Render newest first so the user sees the latest company at the top.
    const reversed = processed.slice().reverse();
    listEl.innerHTML = reversed.map((p, idx) => {
        const num = processed.length - idx;
        if (p.error) {
            return `<div style="padding: 3px 0; display: flex; justify-content: space-between; gap: 8px;">
                <span><span style="color: var(--text-muted);">${num}.</span> ${_escapeHtml(p.name)}</span>
                <span style="color: #ef4444; font-size: 0.75rem;">error</span>
            </div>`;
        }
        const newCount = p.new || 0;
        const tag = newCount > 0
            ? `<span style="color: #10b981;">+${newCount} new</span>`
            : `<span style="color: var(--text-muted);">no new</span>`;
        const dupes = p.duplicate ? ` <span style="color: var(--text-muted); font-size: 0.72rem;">(${p.duplicate} dup)</span>` : '';
        return `<div style="padding: 3px 0; display: flex; justify-content: space-between; gap: 8px;">
            <span><span style="color: var(--text-muted);">${num}.</span> ${_escapeHtml(p.name)}</span>
            <span style="font-size: 0.78rem;">${tag}${dupes}</span>
        </div>`;
    }).join('');
}

async function refreshIngestionLogs() {
    try {
        const res = await fetch(`${API}/api/ingest/logs`);
        const data = await res.json();
        const panel = document.getElementById('ingestion-log-panel');
        if (panel && data.lines) {
            panel.textContent = data.lines.slice(-50).join('\n');
            panel.scrollTop = panel.scrollHeight;
        }
    } catch (e) { /* non-fatal */ }
}

// ========== DIGEST ==========

function _digestEscape(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderDigestData(digest) {
    const companies = digest.companies || [];
    const periodStart = digest.period_start || '';
    const periodEnd = digest.period_end || '';
    const periodDays = digest.period_days || digest.period_days;
    const periodLabel = periodStart && periodEnd
        ? `${periodStart} → ${periodEnd}`
        : periodDays ? `Last ${periodDays} days` : '';
    const generatedAt = digest.created_at
        ? new Date(digest.created_at).toLocaleString()
        : '';
    const itemCount = digest.items_count != null ? digest.items_count : '';

    const metaBar = `
 <div class="digest-meta-bar">
 <span class="digest-meta-period"> ${_digestEscape(periodLabel)}</span>
 <span class="digest-meta-sep">·</span>
 <span>${companies.length} companies</span>
            ${itemCount !== '' ? `<span class="digest-meta-sep">·</span><span>${itemCount} content items</span>` : ''}
            ${generatedAt ? `<span class="digest-meta-sep">·</span><span>Generated ${_digestEscape(generatedAt)}</span>` : ''}
 </div>`;

    if (digest.legacy) {
        return metaBar + `
 <div class="empty-state">
 <div class="icon"></div>
 <h3>Digest format outdated</h3>
 <p>Click "Generate Digest" to create an updated per-company digest.</p>
 </div>`;
    }

    if (!companies.length) {
        return metaBar + `
 <div class="empty-state">
 <div class="icon"></div>
 <h3>No company activity found in this period</h3>
 <p>Try a longer timeframe or run ingestion to pull in recent content.</p>
 </div>`;
    }

    const cards = companies.map(c => {
        const sections = [
            { label: ' Key Updates',                items: c.key_updates },
            { label: ' LinkedIn & Founder Activity', items: c.linkedin_activity },
            { label: ' News & Web Mentions',         items: c.news_mentions },
            { label: ' Opportunities',               items: c.opportunities },
            { label: ' Risks & Concerns',            items: c.risks },
        ].filter(s => Array.isArray(s.items) && s.items.length > 0);

        const hasContent = sections.length > 0 || c.next_action;

        if (!hasContent) {
            return `
 <div class="stat-card company-digest-card company-digest-empty">
 <div class="company-digest-header">
 <h3 class="company-digest-name">${_digestEscape(c.company)}</h3>
 </div>
 <p class="company-digest-no-activity">No notable activity in this period.</p>
 </div>`;
        }

        const sectionsHtml = sections.map(s => `
 <div class="company-digest-section">
 <div class="company-digest-section-label">${s.label}</div>
 <ul>${s.items.map(i => `<li>${_digestEscape(String(i))}</li>`).join('')}</ul>
 </div>`).join('');

        const nextAction = c.next_action ? `
 <div class="company-digest-action">
 <span class="company-digest-action-label">Recommended Next Action</span>
 <span class="company-digest-action-text">${_digestEscape(String(c.next_action))}</span>
 </div>` : '';

        return `
 <div class="stat-card company-digest-card">
 <div class="company-digest-header">
 <h3 class="company-digest-name">${_digestEscape(c.company)}</h3>
 </div>
 <div class="company-digest-body">
                    ${sectionsHtml}
                    ${nextAction}
 </div>
 </div>`;
    }).join('');

    return metaBar + `<div class="company-digest-grid">${cards}</div>`;
}

async function loadDigest() {
    const container = document.getElementById('digest-content');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><span>Loading digest...</span></div>';

    try {
        const days = document.getElementById('digest-timeframe')?.value || '7';
        const res = await fetch(`${API}/api/summaries/digest/current?days=${days}`);
        const data = await res.json();

        if (!data.digest) {
            container.innerHTML = `
 <div class="empty-state">
 <div class="icon"></div>
 <h3>No digest generated yet</h3>
 <p>Select a timeframe above and click "Generate Digest" to create your first portfolio digest.</p>
 </div>`;
            return;
        }

        container.innerHTML = renderDigestData(data.digest);
    } catch (e) {
        container.innerHTML = '<div class="empty-state"><div class="icon"></div><h3>Failed to load digest</h3></div>';
    }
}

async function generateDigest() {
    const container = document.getElementById('digest-content');
    const days = document.getElementById('digest-timeframe')?.value || '7';
    container.innerHTML = `<div class="loading"><div class="spinner"></div><span>Generating ${days}-day digest — this may take up to a minute...</span></div>`;

    try {
        const res = await fetch(`${API}/api/summaries/digest?days=${days}`);
        if (!res.ok) throw new Error('Generation failed');
        const data = await res.json();

        const digestRow = {
            period_days:      data.period_days,
            period_start:     data.period_start,
            period_end:       data.period_end,
            items_count:      data.items_count,
            companies_count:  data.companies_count,
            created_at:       new Date().toISOString(),
            companies:        data.companies,
        };

        container.innerHTML = renderDigestData(digestRow);
        showToast(data.updated_existing ? 'Digest updated!' : 'Digest generated!', 'success');
    } catch (e) {
        container.innerHTML = '<div class="empty-state"><div class="icon"></div><h3>Failed to generate digest</h3></div>';
        showToast('Failed to generate digest', 'error');
    }
}

// ========== SOURCES ==========

async function loadSources() {
    const container = document.getElementById('sources-list');
    container.innerHTML = '<div class="loading"><div class="spinner"></div><span>Loading sources...</span></div>';

    try {
        const res = await fetch(`${API}/api/sources`);
        const data = await res.json();

        container.innerHTML = data.sources.map(s => `
 <div class="content-card">
 <div class="content-card-header">
 <div class="content-card-title">
                        ${s.url ? `<a href="${s.url}" target="_blank">${s.name}</a>` : s.name}
 </div>
 <div style="display: flex; gap: 8px; align-items: center;">
 <span class="tag tag-${s.type}">${s.type}</span>
 <span style="font-size: 0.75rem; color: ${s.is_active ? 'var(--success)' : 'var(--danger)'};">
                            ${s.is_active ? '● Active' : '○ Inactive'}
 </span>
 </div>
 </div>
 <div class="content-card-meta">
 <span class="meta-item">⭐ Priority: ${s.priority}/5</span>
 <span class="meta-item"> ${s.item_count || 0} items</span>
                    ${s.rss_feed_url ? `<span class="meta-item">RSS</span>` : ''}
                    ${s.last_fetched_at ? `<span class="meta-item">Last: ${new Date(s.last_fetched_at).toLocaleDateString()}</span>` : ''}
 </div>
 </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<div class="empty-state"><div class="icon"></div><h3>Failed to load sources</h3></div>';
    }
}

// ========== SOURCES ==========

function showAddSource() {
    document.getElementById('modal-add-source').classList.add('active');
    document.getElementById('source-name').value = '';
    document.getElementById('source-url').value = '';
    document.getElementById('source-rss').value = '';
    document.getElementById('source-priority').value = '3';
}

async function submitAddSource() {
    const name = document.getElementById('source-name').value.trim();
    if (!name) {
        showToast('Name is required', 'error');
        return;
    }

    const body = {
        name,
        type: document.getElementById('source-type').value,
        url: document.getElementById('source-url').value.trim() || null,
        rss_feed_url: document.getElementById('source-rss').value.trim() || null,
        priority: parseInt(document.getElementById('source-priority').value) || 3,
    };

    try {
        const res = await fetch(`${API}/api/sources`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            showToast('Source added!', 'success');
            closeModal('modal-add-source');
            loadSources();
        } else {
            const err = await res.json();
            showToast(err.detail || 'Failed to add source', 'error');
        }
    } catch (e) {
        showToast('Failed to add source', 'error');
    }
}

// ========== MANUAL CONTENT ==========

function showAddContent() {
    document.getElementById('modal-add-content').classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

async function submitManualContent() {
    const title = document.getElementById('manual-title').value.trim();
    const content = document.getElementById('manual-content').value.trim();
    const sourceType = document.getElementById('manual-source-type').value;
    const sourceName = document.getElementById('manual-source-name').value.trim();
    const url = document.getElementById('manual-url').value.trim();

    if (!title || !content) {
        showToast('Title and content are required', 'error');
        return;
    }

    try {
        const res = await fetch(`${API}/api/content`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title, content, source_type: sourceType,
                source_name: sourceName || 'Manual', url
            })
        });

        if (res.ok) {
            showToast('Content added successfully!', 'success');
            closeModal('modal-add-content');
            loadContent();
        } else {
            const err = await res.json();
            showToast(err.detail || 'Failed to add content', 'error');
        }
    } catch (e) {
        showToast('Failed to add content', 'error');
    }
}

// ========== UTILITIES ==========

async function deleteContent(contentId, btnEl) {
    try {
        const res = await fetch(`${API}/api/content/${contentId}`, { method: 'DELETE' });
        if (res.ok) {
            const card = btnEl.closest('.content-card');
            if (card) {
                // Real-time UI decrement
                const group = card.closest('.company-group');
                if (group) {
                    const countEl = group.querySelector('.article-count-text');
                    if (countEl) {
                        const match = countEl.textContent.match(/(\d+)/);
                        if (match) {
                            const newCount = parseInt(match[1]) - 1;
                            countEl.textContent = `${newCount} article${newCount !== 1 ? 's' : ''} found`;
                            if (newCount === 0) {
                                setTimeout(() => group.remove(), 300);
                            }
                            
                            // Also update the 'View all X ->' button if it exists
                            const viewAllEl = group.querySelector('.view-all-text');
                            if (viewAllEl) {
                                if (newCount <= 5) {
                                    viewAllEl.style.display = 'none'; // Hide if no extra articles to view
                                } else {
                                    viewAllEl.textContent = `View all ${newCount} →`;
                                }
                            }
                        }
                    }
                }

                card.style.transition = 'opacity 0.3s, transform 0.3s';
                card.style.opacity = '0';
                card.style.transform = 'translateX(20px)';
                setTimeout(() => card.remove(), 300);
            }
            showToast('Item deleted', 'success');
        } else {
            showToast('Failed to delete item', 'error');
        }
    } catch (e) {
        showToast('Failed to delete item', 'error');
    }
}

async function clearAllContent() {
    if (!confirm('Are you absolutely sure you want to permanently delete ALL articles across the entire dashboard?')) {
        return;
    }
    
    try {
        const btn = document.querySelector('button[onclick="clearAllContent()"]');
        if (btn) btn.textContent = '⏳ Clearing...';
        
        const res = await fetch(`${API}/api/content/all`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Dashboard cleared successfully', 'success');
            loadDashboard(); // Fully resets the UI
        } else {
            showToast('Failed to clear dashboard', 'error');
        }
        
        if (btn) btn.innerHTML = ' Clear All';
    } catch (e) {
        showToast('Error clearing dashboard', 'error');
    }
}

function renderMarkdown(text) {
    if (!text) return '';
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/^### (.*$)/gm, '<h4>$1</h4>')
        .replace(/^## (.*$)/gm, '<h3>$1</h3>')
        .replace(/^# (.*$)/gm, '<h2>$1</h2>')
        .replace(/^- (.*$)/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
        .replace(/\n\n/g, '<br><br>')
        .replace(/\n/g, '<br>');
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Close modal on overlay click
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.classList.remove('active');
    });
});

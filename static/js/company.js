/**
 * Company Detail Page Logic
 */

const API = '';
const startupId = window.location.pathname.split('/company/')[1];

// ========== THEME ==========
function initTheme() {
    const saved = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = saved === 'dark' ? '☀️' : '🌙';
}
function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = next === 'dark' ? '☀️' : '🌙';
}
initTheme();

document.addEventListener('DOMContentLoaded', () => {
    if (startupId) {
        loadCompanyData();
    }
});

async function loadCompanyData() {
    try {
        const res = await fetch(`${API}/api/startups/${startupId}`);
        if (!res.ok) throw new Error('Not found');
        const data = await res.json();

        renderCompanyHeader(data.startup);
        renderContent(data.content);
        renderStats(data.stats);
        document.title = `${data.startup.name} — Startup Intelligence`;
    } catch (e) {
        document.getElementById('company-header').innerHTML = `
            <div class="empty-state">
                <div class="icon">⚠️</div>
                <h3>Company not found</h3>
                <p><a href="/" style="color: var(--accent-light);">Return to dashboard</a></p>
            </div>`;
    }
}

function renderCompanyHeader(s) {
    const initials = s.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();

    document.getElementById('company-header').innerHTML = `
        <div class="company-header">
            <div class="company-avatar">${initials}</div>
            <div class="company-info" style="flex:1;">
                <h1>${s.name}</h1>
                ${s.legal_name ? `<div class="legal-name">${s.legal_name}</div>` : ''}
                ${s.description ? `<p style="font-size: 0.875rem; color: var(--text-secondary); margin-top: 8px;">${s.description}</p>` : ''}
                <div class="company-meta">
                    ${s.industry ? `<div class="meta-pill">🏭 ${s.industry}</div>` : ''}
                    ${s.secondary_industry ? `<div class="meta-pill">🔬 ${s.secondary_industry}</div>` : ''}
                    ${s.stage ? `<div class="meta-pill">📊 ${s.stage}</div>` : ''}
                    ${s.status ? `<div class="meta-pill">📋 ${s.status}</div>` : ''}
                    ${s.contact_name ? `<div class="meta-pill">👤 ${s.contact_name}</div>` : ''}
                    ${s.contact_email ? `<div class="meta-pill">📧 ${s.contact_email}</div>` : ''}
                    ${s.program_stream ? `<div class="meta-pill">🎓 ${s.program_stream}</div>` : ''}
                    ${s.linkedin_url ? `<a href="${s.linkedin_url}" target="_blank" class="meta-pill" style="text-decoration:none;">🔗 LinkedIn</a>` : ''}
                    ${s.twitter_handle ? `<a href="https://twitter.com/${s.twitter_handle}" target="_blank" class="meta-pill" style="text-decoration:none;">🐦 @${s.twitter_handle}</a>` : ''}
                </div>
            </div>
        </div>`;
}

function renderContent(items) {
    const container = document.getElementById('company-content');

    if (!items || items.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="icon">📭</div>
                <h3>No content collected yet</h3>
                <p>Run an ingestion to start collecting news and social posts for this company.</p>
            </div>`;
        return;
    }

    const classLabel = {
        funding: '💰 Funding', product_launch: '🚀 Product', milestone: '📈 Milestone',
        hiring: '👥 Hiring', partnership: '🤝 Partnership', customer_win: '🎯 Customer',
        general: '📰 General', unclassified: '📋 Unclassified'
    };

    // Friendly labels for url-only items so the user sees attribution clearly.
    const urlKindLabel = {
        founder_post_url:        '🧑 Founder LinkedIn post',
        cofounder_post_url:      '🧑 Co-founder LinkedIn post',
        company_post_url:        '🏢 Company LinkedIn post',
        founder_activity_page:   '🧑 Founder activity page',
        cofounder_activity_page: '🧑 Co-founder activity page',
        company_activity_page:   '🏢 Company activity page',
        founder_profile_url:     '🧑 Founder LinkedIn profile',
        cofounder_profile_url:   '🧑 Co-founder LinkedIn profile',
        company_page_url:        '🏢 Company LinkedIn page',
        news_mention:            '📰 News mention',
        web_mention:             '🌐 Web mention',
    };

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function getRoleAttribution(item) {
        // Prefer metadata_json.person_role; fall back to inferring from classification.
        try {
            if (item.metadata_json) {
                const m = typeof item.metadata_json === 'string' ? JSON.parse(item.metadata_json) : item.metadata_json;
                if (m && m.person_role) return m.person_role;
            }
        } catch (e) { /* ignore */ }
        const c = item.classification || '';
        if (c.startsWith('founder_')) return 'founder';
        if (c.startsWith('cofounder_')) return 'cofounder';
        if (c.startsWith('company_')) return 'company';
        return null;
    }

    container.innerHTML = items.map(item => {
        const date = item.published_at ? new Date(item.published_at).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric'
        }) : 'Unknown date';
        const discovered = item.discovered_at ? new Date(item.discovered_at).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric'
        }) : null;

        if (item.ingestion_status === 'url_only') {
            const kind = urlKindLabel[item.classification] || 'LinkedIn link';
            const role = getRoleAttribution(item);
            const author = item.author_name ? escapeHtml(item.author_name) : '';
            const conf = (item.confidence_score != null) ? Number(item.confidence_score).toFixed(2) : null;
            const isPost = (item.classification || '').endsWith('_post_url');
            const ctaLabel = isPost ? '🔗 Open LinkedIn Post'
                            : (item.classification || '').endsWith('_activity_page') ? '🔗 Open Activity Page'
                            : '🔗 Open Link';
            const sourceLabel = item.external_source === 'manual' ? 'Manual / Monday'
                              : item.external_source === 'google_news_rss' ? 'Auto-discovery (Google News)'
                              : (item.source_name || 'LinkedIn');

            return `
                <div class="content-card" style="border-left: 4px solid #0a66c2;">
                    <div class="content-card-header">
                        <div class="content-card-title">
                            ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener" style="color: #0a66c2;">${escapeHtml(item.title || 'LinkedIn link')}</a>` : escapeHtml(item.title || 'Untitled')}
                        </div>
                        <span class="tag" style="background:#e8f0fe;color:#0a66c2;">${kind}</span>
                    </div>
                    <div style="margin-top:8px;font-size:13px;color:#555;">
                        URL-only — clicking opens LinkedIn directly. Post text is not stored locally.
                    </div>
                    ${item.raw_content ? `<div class="content-card-summary" style="font-size:13px;margin-top:8px;color:#444;">${escapeHtml(item.raw_content)}</div>` : ''}
                    <div style="margin-top: 12px; margin-bottom: 12px;">
                        ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener" class="btn btn-primary" style="background: #0a66c2; color: white; text-decoration: none; padding: 6px 12px; border-radius: 4px; font-weight: 500; display: inline-block;">${ctaLabel}</a>` : ''}
                    </div>
                    <div class="content-card-meta">
                        <span class="meta-item"><span class="icon">📰</span> ${escapeHtml(sourceLabel)}</span>
                        ${author ? `<span class="meta-item"><span class="icon">✍️</span> ${author}</span>` : ''}
                        ${role ? `<span class="meta-item"><span class="icon">🎯</span> ${role}</span>` : ''}
                        <span class="meta-item"><span class="icon">📅</span> ${date}</span>
                        ${discovered ? `<span class="meta-item" title="discovered_at"><span class="icon">🕒</span> found ${discovered}</span>` : ''}
                        ${conf ? `<span class="meta-item" title="confidence_score"><span class="icon">📊</span> conf ${conf}</span>` : ''}
                    </div>
                </div>`;
        }

        return `
            <div class="content-card">
                <div class="content-card-header">
                    <div class="content-card-title">
                        ${item.url ? `<a href="${item.url}" target="_blank">${item.title || 'Untitled'}</a>` : (item.title || 'Untitled')}
                    </div>
                    <span class="tag tag-${item.classification || 'unclassified'}">
                        ${classLabel[item.classification] || 'Unclassified'}
                    </span>
                </div>
                ${item.summary ? `<div class="content-card-summary">${item.summary}</div>` : ''}
                <div class="content-card-meta">
                    <span class="meta-item"><span class="icon">📰</span> ${item.source_name || 'Unknown'}</span>
                    <span class="meta-item"><span class="icon">📅</span> ${date}</span>
                    <span class="tag tag-${item.source_type}">${item.source_type}</span>
                </div>
            </div>`;
    }).join('');
}

function renderStats(stats) {
    const grid = document.getElementById('company-stats-grid');
    const detail = document.getElementById('company-stats-detail');

    if (!stats || Object.keys(stats).length === 0) {
        grid.innerHTML = '';
        detail.innerHTML = '<div class="empty-state"><h3>No stats yet</h3></div>';
        return;
    }

    const total = Object.values(stats).reduce((a, b) => a + b, 0);

    const labels = {
        funding: { emoji: '💰', label: 'Funding' },
        product_launch: { emoji: '🚀', label: 'Product' },
        milestone: { emoji: '📈', label: 'Milestones' },
        hiring: { emoji: '👥', label: 'Hiring' },
        partnership: { emoji: '🤝', label: 'Partnerships' },
        customer_win: { emoji: '🎯', label: 'Customers' },
        general: { emoji: '📰', label: 'General' },
        unclassified: { emoji: '📋', label: 'Unclassified' }
    };

    grid.innerHTML = `
        <div class="stat-card">
            <div class="stat-label">Total Items</div>
            <div class="stat-value">${total}</div>
        </div>
        ${Object.entries(stats).map(([cls, count]) => `
            <div class="stat-card">
                <div class="stat-label">${labels[cls]?.emoji || ''} ${labels[cls]?.label || cls}</div>
                <div class="stat-value">${count}</div>
                <div class="stat-detail">${Math.round(count / total * 100)}% of total</div>
            </div>
        `).join('')}`;
}

// ========== TABS ==========

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('[id^="tab-"]').forEach(t => t.style.display = 'none');

    event.target.classList.add('active');
    document.getElementById(`tab-${tab}`).style.display = 'block';
}

// ========== SUMMARY ==========

async function generateSummary(days) {
    switchTab('summary');
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-btn')[1].classList.add('active');

    const container = document.getElementById('summary-content');
    container.innerHTML = `<div class="loading"><div class="spinner"></div><span>Generating ${days}-day AI summary...</span></div>`;

    try {
        const res = await fetch(`${API}/api/summaries/company/${startupId}?days=${days}`);
        const data = await res.json();

        container.innerHTML = `
            <div class="digest-card">
                <h3>📊 ${data.startup} — ${days}-Day Summary</h3>
                <div class="digest-content">${renderMarkdown(data.summary)}</div>
                <div style="margin-top: 1rem; font-size: 0.75rem; color: var(--text-muted);">
                    Based on ${data.items_count} content items.
                </div>
            </div>`;

        showToast('Summary generated!', 'success');
    } catch (e) {
        container.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div><h3>Failed to generate summary</h3></div>';
        showToast('Failed to generate summary', 'error');
    }
}

// ========== UTILS ==========

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
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

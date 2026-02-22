// ── File Guessr - Frontend JavaScript ──

const API = '';

// ── State ──
let isSearching = false;
let pollingInterval = null;
let selectedFolderPath = null;
let attachedFile = null;

// ── Initialize ──
document.addEventListener('DOMContentLoaded', () => {
    checkHealth();

    // Enter key to search
    document.getElementById('search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSearch();
    });

    // Drag & drop on search box
    const searchBox = document.querySelector('.search-box');
    searchBox.addEventListener('dragover', (e) => {
        e.preventDefault();
        searchBox.classList.add('drag-over');
    });
    searchBox.addEventListener('dragleave', () => {
        searchBox.classList.remove('drag-over');
    });
    searchBox.addEventListener('drop', (e) => {
        e.preventDefault();
        searchBox.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) {
            setAttachedFile(e.dataTransfer.files[0]);
        }
    });
});

// ── Health Check ──
async function checkHealth() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    try {
        const res = await fetch(`${API}/api/health`);
        const data = await res.json();
        if (data.ollama_running && data.model_available) {
            dot.className = 'status-dot online';
            text.textContent = 'Ollama OK';
        } else if (data.ollama_running) {
            dot.className = 'status-dot offline';
            text.textContent = 'Model not found';
        } else {
            dot.className = 'status-dot offline';
            text.textContent = 'Ollama offline';
        }
    } catch {
        dot.className = 'status-dot offline';
        text.textContent = 'Server offline';
    }
}

// ── File Attachment ──
function onFileAttached(input) {
    if (input.files.length > 0) {
        setAttachedFile(input.files[0]);
    }
}

function setAttachedFile(file) {
    attachedFile = file;
    const container = document.getElementById('attached-file');
    const nameEl = document.getElementById('attached-name');
    const iconEl = container.querySelector('.attached-icon');

    // Set icon based on type
    if (file.type.startsWith('image/')) {
        iconEl.textContent = '🖼️';
    } else if (file.name.endsWith('.pdf')) {
        iconEl.textContent = '📕';
    } else if (file.name.endsWith('.docx')) {
        iconEl.textContent = '📘';
    } else {
        iconEl.textContent = '📄';
    }

    nameEl.textContent = file.name;
    container.style.display = 'flex';
}

function removeAttachment() {
    attachedFile = null;
    document.getElementById('attached-file').style.display = 'none';
    document.getElementById('search-file-input').value = '';
}

// ── Search ──
async function doSearch() {
    const input = document.getElementById('search-input');
    const query = input.value.trim();
    if ((!query && !attachedFile) || isSearching) return;

    isSearching = true;
    const btn = document.getElementById('btn-search');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';

    const meta = document.getElementById('search-meta');
    meta.innerHTML = '搜尋中... (LLM 正在分析' + (attachedFile ? '檔案和文字' : '關鍵字') + ')';

    const results = document.getElementById('results');
    results.innerHTML = '';

    try {
        let data;

        if (attachedFile) {
            // Multimodal search: file + text
            const formData = new FormData();
            formData.append('file', attachedFile);
            formData.append('q', query);

            const res = await fetch(`${API}/api/search/multimodal`, {
                method: 'POST',
                body: formData,
            });
            data = await res.json();

            if (!res.ok) {
                throw new Error(data.error || 'Search failed');
            }
        } else {
            // Text-only search
            const res = await fetch(`${API}/api/search?q=${encodeURIComponent(query)}`);
            data = await res.json();
        }

        // Show expanded query
        const fileTag = data.uploaded_file
            ? ` + <span class="attached-tag">📎 ${escapeHtml(data.uploaded_file)}</span>`
            : '';
        meta.innerHTML = `找到 <strong>${data.total_results}</strong> 個結果${fileTag} — 
            展開關鍵字: <span class="expanded-query">${escapeHtml(data.expanded_query)}</span>`;

        if (data.results.length === 0) {
            results.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🤷</div>
                    <h2>沒有找到相關檔案</h2>
                    <p>試試不同的描述方式，或確認資料夾已被索引</p>
                </div>`;
        } else {
            results.innerHTML = data.results.map((r, i) => renderResult(r, i, data.expanded_query)).join('');
        }
    } catch (err) {
        meta.innerHTML = `<span class="text-error">搜尋失敗: ${err.message}</span>`;
    } finally {
        isSearching = false;
        btn.disabled = false;
        btn.innerHTML = '搜尋';
    }
}

function renderResult(r, index, query) {
    const icon = getFileIcon(r.file_type);
    const isImage = isImageType(r.file_type);
    const size = formatSize(r.file_size);
    const keywords = (r.keywords || '').split(' ').filter(k => k);

    // Highlight logic
    const queryTerms = query ? query.toLowerCase().split(/\s+/) : [];

    const highlight = (text) => {
        if (!text) return '';
        if (!queryTerms.length) return escapeHtml(text);

        let result = escapeHtml(text);
        queryTerms.forEach(term => {
            if (term.length < 2) return;
            const regex = new RegExp(`(${term})`, 'gi');
            result = result.replace(regex, '<span class="highlight">$1</span>');
        });
        return result;
    };

    const highlightedSummary = highlight(r.summary);

    // Sort keywords: matches first
    keywords.sort((a, b) => {
        const aMatch = queryTerms.some(t => a.toLowerCase().includes(t));
        const bMatch = queryTerms.some(t => b.toLowerCase().includes(t));
        return bMatch - aMatch;
    });

    const displayKeywords = keywords.slice(0, 20).map(k => {
        const isMatch = queryTerms.some(t => k.toLowerCase().includes(t));
        return `<span class="tag ${isMatch ? 'highlight' : ''}">${escapeHtml(k)}</span>`;
    }).join('');

    const delay = index * 0.05;

    let imagePreview = '';
    if (isImage) {
        imagePreview = `<img class="result-image-preview" 
            src="${API}/api/file/preview?path=${encodeURIComponent(r.file_path)}" 
            alt="${escapeHtml(r.file_name)}"
            loading="lazy"
            onerror="this.style.display='none'">`;
    }

    return `
        <div class="result-card" style="animation-delay: ${delay}s" 
             ondblclick="openFile('${escapeAttr(r.file_path)}')">
            ${imagePreview}
            <div class="result-header">
                <div class="result-icon">${icon}</div>
                <div class="result-title">
                    <h3>${escapeHtml(r.file_name)}</h3>
                    <div class="result-path" title="${escapeAttr(r.file_path)}">${escapeHtml(r.file_path)}</div>
                </div>
            </div>
            <div class="result-summary">${highlightedSummary || 'No summary available'}</div>
            <div class="result-tags">
                ${displayKeywords}
            </div>
            <div class="result-meta">
                <span>${r.file_type || 'unknown'}</span>
                <span>${size}</span>
            </div>
        </div>`;
}

// ── Folder Picker ──
async function browseFolderPath() {
    const btn = document.getElementById('btn-browse');
    const pathDisplay = document.getElementById('selected-folder-path');
    const indexBtn = document.getElementById('btn-index');

    btn.disabled = true;
    btn.textContent = '⏳ 開啟中...';

    try {
        const res = await fetch(`${API}/api/browse`);
        const data = await res.json();

        if (data.path) {
            selectedFolderPath = data.path;
            pathDisplay.textContent = data.path;
            pathDisplay.classList.add('has-path');
            indexBtn.disabled = false;
        } else {
            // User cancelled
        }
    } catch (err) {
        alert('無法開啟資料夾選擇器: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '📂 選擇資料夾';
    }
}

// ── Indexing ──
async function startIndex() {
    if (!selectedFolderPath) return alert('請先選擇資料夾');

    const btn = document.getElementById('btn-index');
    btn.disabled = true;

    try {
        const res = await fetch(`${API}/api/index`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path: selectedFolderPath }),
        });
        const data = await res.json();

        if (!res.ok) {
            alert(data.error || 'Failed to start indexing');
            btn.disabled = false;
            return;
        }

        // Show progress and start polling
        document.getElementById('progress-card').style.display = 'block';
        startPolling();
    } catch (err) {
        alert('Error: ' + err.message);
        btn.disabled = false;
    }
}

function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(updateProgress, 1000);
}

async function updateProgress() {
    try {
        const res = await fetch(`${API}/api/index/status`);
        const data = await res.json();

        const pct = data.total_files > 0
            ? Math.round((data.processed_files / data.total_files) * 100)
            : 0;

        document.getElementById('progress-bar').style.width = `${pct}%`;
        document.getElementById('progress-text').textContent =
            `${data.processed_files} / ${data.total_files} (${pct}%)`;
        document.getElementById('progress-file').textContent = data.current_file || '-';
        document.getElementById('progress-time').textContent =
            `已耗時: ${data.elapsed_seconds}s`;

        if (data.errors && data.errors.length > 0) {
            document.getElementById('progress-errors').textContent =
                `${data.errors.length} 個錯誤`;
        }

        if (!data.is_indexing && data.total_files > 0) {
            clearInterval(pollingInterval);
            pollingInterval = null;
            document.getElementById('btn-index').disabled = false;
            loadStats();
            loadWatchedFolders();
        }
    } catch {
        // ignore
    }
}

// ── Watched Folders ──
async function loadWatchedFolders() {
    const container = document.getElementById('watched-folders-list');
    try {
        const res = await fetch(`${API}/api/folders`);
        const data = await res.json();

        if (!data.folders || data.folders.length === 0) {
            container.innerHTML = '<p class="text-muted">尚未新增任何資料夾</p>';
            return;
        }

        container.innerHTML = data.folders.map(f => `
            <div class="watched-folder-item">
                <span class="watched-folder-path" title="${escapeAttr(f)}">📁 ${escapeHtml(f)}</span>
                <button class="btn-remove-folder" onclick="removeFolder('${escapeAttr(f)}')" title="移除此資料夾">
                    🗑️
                </button>
            </div>
        `).join('');
    } catch {
        container.innerHTML = '<p class="text-error">無法載入資料夾清單</p>';
    }
}

async function removeFolder(path) {
    if (!confirm(`確定要移除此資料夾的索引嗎？\n\n${path}`)) return;

    try {
        const res = await fetch(`${API}/api/folders/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path: path }),
        });
        const data = await res.json();
        if (res.ok) {
            loadWatchedFolders();
            loadStats();
        } else {
            alert(data.error || 'Failed to remove folder');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// ── Stats ──
async function loadStats() {
    const container = document.getElementById('stats-content');
    try {
        const res = await fetch(`${API}/api/stats`);
        const data = await res.json();

        if (data.total_files === 0) {
            container.innerHTML = '<p class="text-muted">尚未索引任何檔案</p>';
            return;
        }

        const typeItems = Object.entries(data.by_type)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10)
            .map(([type, count]) => `
                <div class="stat-item">
                    <div class="stat-value">${count}</div>
                    <div class="stat-label">${type || 'no ext'}</div>
                </div>`)
            .join('');

        const esStatus = data.search_engine === 'elasticsearch'
            ? '<span class="es-badge online">🟢 Elasticsearch</span>'
            : '<span class="es-badge offline">🟡 SQLite Fallback</span>';

        container.innerHTML = `
            <div class="stats-header">${esStatus}</div>
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-value">${data.total_files}</div>
                    <div class="stat-label">總檔案數</div>
                </div>
                ${typeItems}
            </div>`;
    } catch {
        container.innerHTML = '<p class="text-error">無法載入統計</p>';
    }
}

async function clearIndex() {
    if (!confirm('確定要清除所有索引資料嗎？')) return;
    try {
        await fetch(`${API}/api/clear`, { method: 'POST' });
        loadStats();
        loadWatchedFolders();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// ── Panel ──
function showPanel(name) {
    document.getElementById('panel-overlay').classList.add('active');
    document.getElementById(`panel-${name}`).classList.add('active');
    if (name === 'settings') {
        loadStats();
        loadWatchedFolders();
    }
}

function hidePanel() {
    document.getElementById('panel-overlay').classList.remove('active');
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
}

// Close panel on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hidePanel();
});

// ── Helpers ──
function getFileIcon(ext) {
    const icons = {
        '.pdf': '📕', '.docx': '📘', '.doc': '📘', '.xlsx': '📊', '.xls': '📊',
        '.pptx': '📙', '.ppt': '📙',
        '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️', '.webp': '🖼️',
        '.bmp': '🖼️', '.svg': '🖼️', '.tiff': '🖼️', '.ico': '🖼️',
        '.py': '🐍', '.js': '📜', '.ts': '📜', '.html': '🌐', '.css': '🎨',
        '.java': '☕', '.cpp': '⚙️', '.c': '⚙️', '.go': '🔵', '.rs': '🦀',
        '.txt': '📄', '.md': '📝', '.json': '📋', '.xml': '📋', '.csv': '📊',
        '.yaml': '📋', '.yml': '📋', '.log': '📃',
        '.zip': '📦', '.rar': '📦', '.7z': '📦',
        '.mp3': '🎵', '.wav': '🎵', '.mp4': '🎬', '.avi': '🎬',
    };
    return icons[ext] || '📄';
}

function isImageType(ext) {
    return ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.ico'].includes(ext);
}

function formatSize(bytes) {
    if (!bytes) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        i++;
    }
    return `${size.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/'/g, "\\'").replace(/\\/g, "\\\\");
}

function openFile(path) {
    navigator.clipboard.writeText(path).then(() => {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
            background: var(--bg-elevated); color: var(--text-primary);
            padding: 10px 20px; border-radius: 8px; font-size: 0.85rem;
            border: 1px solid var(--border); box-shadow: var(--shadow);
            z-index: 200; animation: fadeInUp 0.3s ease;
        `;
        toast.textContent = `📋 路徑已複製: ${path}`;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2500);
    });
}

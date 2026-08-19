/* 笔驭 BiYu — 前端逻辑 */

const API = '';
let currentBook = null;
let currentChapter = null;

// ── 初始化 ──────────────────────────────────────────────────────────────────

async function init() {
    await loadBooks();
    document.getElementById('book-list').addEventListener('change', onBookChange);
}

async function loadBooks() {
    const res = await fetch(`${API}/api/books`);
    // F3 (P8-M3R-fix):/api/books 返 dict schema {books, count}
    const books = (await res.json()).books;
    const sel = document.getElementById('book-list');
    sel.innerHTML = '<option value="">选择一本书...</option>';
    books.forEach(b => {
        const opt = document.createElement('option');
        opt.value = b.name;
        opt.textContent = b.title || b.name;
        sel.appendChild(opt);
    });
}

async function onBookChange() {
    const sel = document.getElementById('book-list');
    currentBook = sel.value;
    currentChapter = null;
    if (!currentBook) return;
    await loadChapters();
    showWelcome();
}

async function loadChapters() {
    if (!currentBook) return;
    const res = await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/chapters`);
    const chapters = await res.json();
    const list = document.getElementById('chapter-list');
    list.innerHTML = '';

    chapters.forEach(ch => {
        const div = document.createElement('div');
        div.className = 'ch-item';
        div.dataset.chapter = ch.chapter;
        let badges = '';
        if (ch.has_content) badges += '<span class="badge ok">已生成</span>';
        else if (ch.has_outline) badges += '<span class="badge">待生成</span>';
        div.innerHTML = `<span>第${ch.chapter}章</span>${badges}`;
        div.onclick = () => selectChapter(ch.chapter);
        list.appendChild(div);
    });
}

// ── 章节选择 ────────────────────────────────────────────────────────────────

async function selectChapter(n) {
    currentChapter = n;

    // 高亮
    document.querySelectorAll('.ch-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.chapter) === n);
    });

    document.getElementById('welcome').style.display = 'none';
    document.getElementById('editor').style.display = '';
    document.getElementById('editor-title').textContent = `第 ${n} 章`;

    // 加载大纲
    const outlineRes = await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/chapters/${n}/outline`);
    if (outlineRes.ok) {
        const data = await outlineRes.json();
        document.getElementById('outline-text').value = data.content || '';
    } else {
        document.getElementById('outline-text').value = '';
    }

    // 加载正文
    const contentRes = await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/chapters/${n}/content`);
    if (contentRes.ok) {
        const data = await contentRes.json();
        document.getElementById('content-display').textContent = data.content || '';
    } else {
        document.getElementById('content-display').textContent = '（未生成）';
    }

    // 加载元数据
    const metaRes = await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/chapters/${n}/outline`);
    try {
        const bk = currentBook;
        const metaPath = `${API}/api/books/${encodeURIComponent(bk)}/chapters`;
        // 元数据从 chapters 列表获取
        const chList = await (await fetch(metaPath)).json();
        const chInfo = chList.find(c => c.chapter === n);
        document.getElementById('meta-display').textContent = chInfo ? JSON.stringify(chInfo, null, 2) : '（无）';
    } catch {
        document.getElementById('meta-display').textContent = '（无）';
    }

    switchTab('outline');
}

// ── Tab 切换 ────────────────────────────────────────────────────────────────

function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
    document.getElementById(`tab-${tab}`).classList.add('active');
    // 切到审读 tab 时,自动加载该章已有的问题卡
    if (tab === 'review' && currentBook && currentChapter) {
        loadReview();
    }
}

// ── 大纲保存 ────────────────────────────────────────────────────────────────

async function saveOutline() {
    if (!currentBook || !currentChapter) return;
    const content = document.getElementById('outline-text').value;
    await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/chapters/${currentChapter}/outline`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({content}),
    });
    alert('大纲已保存');
    await loadChapters();
}

// ── 生成章节 ────────────────────────────────────────────────────────────────

async function generateChapter() {
    if (!currentBook || !currentChapter) return;

    const progressPanel = document.getElementById('progress-panel');
    const progressLog = document.getElementById('progress-log');
    progressPanel.style.display = '';
    progressLog.innerHTML = '';

    const evtSource = new EventSource(
        `${API}/api/books/${encodeURIComponent(currentBook)}/chapters/${currentChapter}/generate`
    );

    evtSource.onmessage = (e) => {
        if (e.data === '[DONE]') {
            evtSource.close();
            addProgress(progressLog, '生成完成', 'done');
            loadChapters();
            selectChapter(currentChapter);
            return;
        }
        try {
            const data = JSON.parse(e.data);
            if (data.type === 'progress') {
                addProgress(progressLog, `[${data.stage}] ${data.message}`);
            } else if (data.type === 'done') {
                addProgress(progressLog, `完成: ${data.word_count}字, ¥${data.cost_cny?.toFixed(4)}`, 'done');
            } else if (data.type === 'error') {
                addProgress(progressLog, `错误: ${data.error}`, 'error');
            }
        } catch {}
    };

    evtSource.onerror = () => {
        evtSource.close();
        addProgress(progressLog, '连接断开', 'error');
    };
}

// ── 一致性检查 ──────────────────────────────────────────────────────────────

async function checkChapter() {
    if (!currentBook || !currentChapter) return;
    const res = await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/chapters/${currentChapter}/check`, {
        method: 'POST',
    });
    const data = await res.json();
    if (data.issues && data.issues.length > 0) {
        alert(`发现 ${data.issues.length} 个问题:\n` + data.issues.map(i => `- [${i.severity}] ${i.character}: ${i.rule}`).join('\n'));
    } else {
        alert('一致性检查通过');
    }
}

// ── 刷新设定 ────────────────────────────────────────────────────────────────

async function refreshChapter() {
    if (!currentBook || !currentChapter) return;
    const res = await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/chapters/${currentChapter}/refresh`, {
        method: 'POST',
    });
    const data = await res.json();
    alert(data.success ? '设定刷新成功' : '设定刷新失败');
}

// ── 批量生成 ────────────────────────────────────────────────────────────────

function startAutoGenerate() {
    if (!currentBook) { alert('请先选择一本书'); return; }

    const fromVal = prompt('起始章节号:');
    const toVal = prompt('结束章节号:');
    if (!fromVal || !toVal) return;

    const progressPanel = document.getElementById('progress-panel');
    const progressLog = document.getElementById('progress-log');
    progressPanel.style.display = '';
    progressLog.innerHTML = '';

    fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/auto`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({from: parseInt(fromVal), to: parseInt(toVal)}),
    }).then(res => {
        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        function read() {
            reader.read().then(({done, value}) => {
                if (done) {
                    addProgress(progressLog, '批量生成结束', 'done');
                    loadChapters();
                    return;
                }
                const text = decoder.decode(value);
                text.split('\n').forEach(line => {
                    if (line.startsWith('data: ') && line !== 'data: [DONE]') {
                        try {
                            const data = JSON.parse(line.slice(6));
                            if (data.type === 'chapter_done') {
                                addProgress(progressLog, `ch${data.chapter} 完成: ${data.word_count}字, ¥${data.cost_cny?.toFixed(4)}`, 'done');
                            } else if (data.type === 'all_done') {
                                addProgress(progressLog, `全部完成: ${data.total}章, 总成本 ¥${data.total_cost?.toFixed(4)}`, 'done');
                            } else if (data.type === 'error') {
                                addProgress(progressLog, `错误: ${data.error}`, 'error');
                            }
                        } catch {}
                    }
                });
                read();
            });
        }
        read();
    });
}

// ── 刷新列表 ────────────────────────────────────────────────────────────────

async function refreshAll() {
    await loadBooks();
    if (currentBook) await loadChapters();
}

// ── P8-M2 T4:审读(standalone Editor 问题卡)─────────────────────────────────

async function loadReview() {
    /** 切到审读 tab 时调:读已生成的问题卡(若存在),无则显示"未审读"。 */
    if (!currentBook || !currentChapter) return;

    const status = document.getElementById('review-status');
    const display = document.getElementById('review-display');

    const res = await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/reviews/standalone/${currentChapter}`);
    if (res.status === 404) {
        status.textContent = '未审读';
        status.className = 'review-status review-empty';
        display.innerHTML = '<p class="review-empty">点击「审读此章」开始,或选择已有问题卡的章节。</p>';
        return;
    }
    if (!res.ok) {
        status.textContent = `加载失败(${res.status})`;
        status.className = 'review-status review-error';
        return;
    }
    const data = await res.json();
    renderReviewMarkdown(data.markdown);
}

async function triggerReview() {
    /** 触发 standalone 审读:POST → 落盘 + 返摘要 + 渲染 markdown。 */
    if (!currentBook || !currentChapter) return;

    const btn = document.getElementById('btn-run-review');
    const status = document.getElementById('review-status');
    const display = document.getElementById('review-display');

    btn.disabled = true;
    status.textContent = '审读中...(Editor 多轮调用,约 10-30 秒)';
    status.className = 'review-status review-running';
    display.innerHTML = '';

    try {
        const res = await fetch(
            `${API}/api/books/${encodeURIComponent(currentBook)}/reviews/standalone/${currentChapter}`,
            { method: 'POST' },
        );
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            status.textContent = `审读失败(${res.status}): ${err.detail || res.statusText}`;
            status.className = 'review-status review-error';
            return;
        }
        const data = await res.json();
        // 摘要头
        const parts = [`Issue ${data.issue_count}`];
        if (data.failures && Object.keys(data.failures).length > 0) {
            parts.push(`失败模式 ${JSON.stringify(data.failures)}`);
        }
        parts.push(`¥${(data.cost || 0).toFixed(4)}`);
        parts.push(`信心 ${data.confidence}`);
        status.textContent = parts.join(' / ');
        status.className = 'review-status review-done';

        renderReviewMarkdown(data.markdown);
    } catch (e) {
        status.textContent = `审读失败: ${e.message || e}`;
        status.className = 'review-status review-error';
    } finally {
        btn.disabled = false;
    }
}

function renderReviewMarkdown(md) {
    /** 渲染审读 Markdown。
     *
     * MVP:不引外部 Markdown 库,直接 <pre> 保留格式(问题卡本身已是
     * 结构化 Markdown,作者习惯看 raw)。后续可加 marked.js 渲染。
     */
    const display = document.getElementById('review-display');
    if (!md) {
        display.innerHTML = '<p class="review-empty">(空)</p>';
        return;
    }
    // 简单 escape + 保留换行
    const escaped = md
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    display.innerHTML = `<pre class="review-md">${escaped}</pre>`;
}

// ── P8-M2 T4:建记忆(refresh 全章 truth_files)──────────────────────────────

async function showBuildMemoryModal() {
    /** 点"建记忆"按钮:先拉成本估算,显示确认弹窗。 */
    if (!currentBook) { alert('请先选择一本书'); return; }

    const modal = document.getElementById('build-memory-modal');
    const text = document.getElementById('build-memory-text');
    const log = document.getElementById('build-memory-log');
    const confirmBtn = document.getElementById('build-memory-confirm');

    modal.hidden = false;
    text.textContent = '估算中...';
    log.innerHTML = '';
    confirmBtn.disabled = true;

    try {
        const res = await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/refresh-estimate`);
        if (!res.ok) {
            text.textContent = `估算失败(${res.status})`;
            return;
        }
        const data = await res.json();
        if (data.chapter_count === 0) {
            text.textContent = '该书暂无章节,无需建记忆。';
            confirmBtn.disabled = true;
            return;
        }
        text.textContent = (
            `共 ${data.chapter_count} 章 × ` +
            `每章 ¥${data.per_chapter_low.toFixed(4)}-${data.per_chapter_high.toFixed(4)} ` +
            `= 估算 ¥${data.total_low.toFixed(4)}-${data.total_high.toFixed(4)}。` +
            ` 软顶 ¥1.5 / 硬停 ¥2.5(spec P8-M2)。`
        );
        confirmBtn.disabled = false;
    } catch (e) {
        text.textContent = `估算失败: ${e.message || e}`;
    }
}

function closeBuildMemoryModal() {
    document.getElementById('build-memory-modal').hidden = true;
}

async function triggerBuildMemory() {
    /** 确认后逐章刷新 truth_files,实时显示进度。 */
    if (!currentBook) return;

    const log = document.getElementById('build-memory-log');
    const confirmBtn = document.getElementById('build-memory-confirm');
    const cancelBtn = document.getElementById('build-memory-cancel');
    confirmBtn.disabled = true;
    cancelBtn.disabled = true;
    log.innerHTML = '';

    const addLine = (text, cls = '') => {
        const div = document.createElement('div');
        div.className = 'progress-line' + (cls ? ' ' + cls : '');
        div.textContent = text;
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
    };

    addLine('开始建记忆...');
    let totalCost = 0;
    let okCount = 0;
    let failCount = 0;

    try {
        // 拿章节列表
        const chRes = await fetch(`${API}/api/books/${encodeURIComponent(currentBook)}/chapters`);
        const chapters = await chRes.json();
        const nums = chapters.filter(c => c.has_content).map(c => c.chapter).sort((a, b) => a - b);
        if (nums.length === 0) {
            addLine('无章节需要刷新', 'done');
            return;
        }

        for (const n of nums) {
            addLine(`ch${n} 刷新中...`);
            try {
                const r = await fetch(
                    `${API}/api/books/${encodeURIComponent(currentBook)}/chapters/${n}/refresh`,
                    { method: 'POST' },
                );
                const d = await r.json();
                if (d.success) {
                    okCount++;
                    addLine(`ch${n} ✓`, 'done');
                } else {
                    failCount++;
                    addLine(`ch${n} ✗`, 'error');
                }
            } catch (e) {
                failCount++;
                addLine(`ch${n} ✗ ${e.message || e}`, 'error');
            }
        }

        addLine(`完成: ${okCount} 成功 / ${failCount} 失败`, 'done');
    } catch (e) {
        addLine(`异常: ${e.message || e}`, 'error');
    } finally {
        cancelBtn.disabled = false;
    }
}

// ── 辅助函数 ────────────────────────────────────────────────────────────────

function addProgress(container, text, cls = '') {
    const div = document.createElement('div');
    div.className = 'progress-line' + (cls ? ' ' + cls : '');
    div.textContent = text;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function showWelcome() {
    document.getElementById('welcome').style.display = '';
    document.getElementById('editor').style.display = 'none';
}

// ── 启动 ────────────────────────────────────────────────────────────────────

init();

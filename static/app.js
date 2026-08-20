const logEl = document.getElementById('log');
const treeEl = document.getElementById('tree');
const reportEl = document.getElementById('report');
const reportSummaryEl = document.getElementById('reportSummary');
const pathInput = document.getElementById('path');
const scanBtn = document.getElementById('scan');
const showTreeBtn = document.getElementById('showTree');
const showReportBtn = document.getElementById('showReport');
const treePanel = document.getElementById('treePanel');
const reportPanel = document.getElementById('reportPanel');
const searchInput = document.getElementById('search');
const filterSel = document.getElementById('filter');
const statusEl = document.getElementById('status');
let treeData = null;
let logOffset = 0;
let pollTimer = null;
let logLines = [];          // 前端日志缓冲（仅用于渲染，最多保留最近 MAX_LOG_RENDER 条）
const MAX_LOG_RENDER = 1000;
let reportCount = 0;        // 报告渲染计数器（用于限流）
const REPORT_MAX = 5000;

const CAT_LABEL = {
  safe: '可直接删', software_clean: '软件内清',
  confirm: '需确认', never: '禁止删', unknown: '未收录',
  ai: 'AI 识别'
};
const CAT_ICON = {
  safe: '🟢', software_clean: '🔵', confirm: '🟡', never: '🔴', unknown: '⚪',
  ai: '🤖'
};
const LV_LABEL = { safe: '🟢 可删除', caution: '🟡 谨慎', never: '🔴 别删' };
const CONF_LABEL = { high: '高', medium: '中', low: '低' };

// 构建「AI 识别」信息块：先醒目展示一句话总结，再列 软件 / 能否删除 / 风险 / 把握
function buildAiBlock(node) {
  const lv = node.level || 'caution';
  const summary = node.summary || node.purpose || node.description || '';
  const box = document.createElement('div');
  box.className = 'ai-block';
  box.innerHTML =
    `<span class="badge cat-ai">🤖 AI 识别</span>` +
    `<span class="badge lvl-${lv}">${LV_LABEL[lv] || '谨慎'}</span>` +
    (node.confidence ? `<span class="muted">把握：${CONF_LABEL[node.confidence] || node.confidence}</span>` : '') +
    (summary ? `<div class="ai-summary"><b>📝 这是什么：</b>${escapeHtml(summary)}</div>` : '') +
    (node.software ? `<div class="ai-line"><b>📦 软件：</b>${escapeHtml(node.software)}</div>` : '') +
    (node.deletable ? `<div class="ai-line"><b>🗑 能否删除：</b>${escapeHtml(node.deletable)}</div>` : '');
  return box;
}

// 点击「🤖 AI分析」：调用服务端 /api/analyze（服务端持 Key），把结果展示在文件夹下方
function analyzeFolder(node, item, btn) {
  if (item.querySelector('.ai-result')) return;   // 已分析过，不重复
  btn.disabled = true;
  btn.textContent = '⏳ 分析中…';
  fetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: node.path, name: node.name, size_human: node.size_human })
  })
    .then(r => {
      if (!r.headers.get('content-type') || !r.headers.get('content-type').includes('application/json')) {
        return r.text().then(t => ({ ok: false, d: { error: '后端返回非 JSON（可能 /api/analyze 不存在），请确认已重启最新版 app.py。响应前 200 字：' + t.slice(0, 200) } }));
      }
      return r.json().then(d => ({ ok: r.ok, d }));
    })
    .then(({ ok, d }) => {
      btn.disabled = false;
      btn.textContent = '🤖 AI分析';
      if (!ok || !d.ok) {
        alert('分析失败：' + (d && d.error ? d.error : '未知错误'));
        return;
      }
      const box = document.createElement('div');
      box.className = 'ai-result';
      box.innerHTML = aiResultBlock(d.result);
      item.appendChild(box);
    })
    .catch(err => {
      btn.disabled = false;
      btn.textContent = '🤖 AI分析';
      alert('分析请求出错：' + err);
    });
}

// 展示单文件夹 AI 分析结果（是什么 / 能否删除 / 删除影响）
function aiResultBlock(r) {
  r = r || {};
  const lv = r.level || 'caution';
  return '<div class="ai-block">' +
    '<span class="badge cat-ai">🤖 AI 分析</span>' +
    `<span class="badge lvl-${lv}">${LV_LABEL[lv] || '谨慎'}</span>` +
    (r.confidence ? `<span class="muted">把握：${CONF_LABEL[r.confidence] || r.confidence}</span>` : '') +
    (r.summary ? `<div class="ai-line"><b>📝 是什么：</b>${escapeHtml(r.summary)}</div>` : '') +
    (r.deletable ? `<div class="ai-line"><b>🗑 能否删除：</b>${escapeHtml(r.deletable)}</div>` : '') +
    (r.impact ? `<div class="ai-line"><b>⚠ 删除影响：</b>${escapeHtml(r.impact)}</div>` : '') +
    '</div>';
}

scanBtn.onclick = startScan;
showTreeBtn.onclick = () => switchView('tree');
showReportBtn.onclick = () => switchView('report');

// 页面加载即尝试恢复服务端已有的扫描结果（解决"刷新后目录树/报告变空白"）
recoverTree();

function switchView(view) {
  if (view === 'report') {
    reportPanel.style.display = 'block';
    treePanel.style.display = 'none';
    showReportBtn.classList.add('active');
    showTreeBtn.classList.remove('active');
    if (treeData) renderReport();   // 首次打开时生成报告
  } else {
    treePanel.style.display = 'block';
    reportPanel.style.display = 'none';
    showTreeBtn.classList.add('active');
    showReportBtn.classList.remove('active');
  }
}

function setStatus(txt, cls) {
  statusEl.textContent = txt;
  statusEl.className = 'status ' + (cls || '');
}

function startScan(force) {
  const path = pathInput.value.trim();
  if (!path) return;
  logLines = [];
  renderLog();
  treeEl.innerHTML = '';
  reportEl.innerHTML = '';
  reportSummaryEl.innerHTML = '';
  treeData = null;
  logOffset = 0;
  showReportBtn.disabled = true;
  switchView('tree');
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  setStatus('请求中…', 'busy');
  fetch('/api/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, force: !!force })
  })
    .then(r => r.json())
    .then(d => {
      if (d.error) {
        pushLog('❌ ' + d.error);
        setStatus('错误', 'err');
        if (d.in_progress) {
          // 已有扫描在进行中：给出「强制重新扫描」入口，取消旧扫描后重启。
          pushLog('⌛ 如需中止当前扫描并重新扫描，请点下方按钮：');
          const btn = document.createElement('button');
          btn.className = 'btn force-scan-btn';
          btn.textContent = '⏹ 强制重新扫描';
          btn.onclick = () => { btn.remove(); startScan(true); };
          logEl.after(btn);
        }
        return;
      }
      pushLog('⏳ 扫描已开始，日志实时刷新（最新在上）…');
      poll();                       // 立即拉一次，避免等 500ms
      pollTimer = setInterval(poll, 500);
    })
    .catch(e => { pushLog('❌ 请求失败：' + e); setStatus('错误', 'err'); });
}

function poll() {
  fetch('/api/status?after=' + logOffset)
    .then(r => r.json())
    .then(s => {
      if (s.logs && s.logs.length) {
        appendLogs(s.logs, s.skipped);
        logOffset = s.log_offset;
      }
      if (s.errored) {
        pushLog('❌ ' + s.error);
        setStatus('扫描出错', 'err');
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        return;
      }
      if (s.scanning) {
        setStatus('扫描中… 已扫 ' + s.progress.dirs + ' 个目录', 'busy');
      } else if (s.done) {
        setStatus('扫描完成 ✓', 'ok');
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        fetchTree();
      } else {
        setStatus('空闲', '');
      }
      // 报告生成后，给出「打开/下载」入口（整盘等超大扫描尤其有用）
      if (s.report_ready && s.report_name && !document.getElementById('reportLink')) {
        const a = document.createElement('a');
        a.id = 'reportLink';
        a.className = 'report-link';
        a.href = '/api/report';
        a.target = '_blank';
        a.textContent = '📄 打开/下载聚焦版 HTML 报告（' + s.report_name + '）';
        logEl.after(a);
      }
    })
    .catch(() => { /* 网络抖动，下一次轮询继续，不报错 */ });
}

// 页面刷新后自动恢复：若服务端已有上次扫描结果，直接重新渲染树与报告，避免一刷新就空白。
function recoverTree() {
  fetch('/api/tree')
    .then(r => r.json())
    .then(d => {
      if (d.ready && d.tree) {
        treeData = d.tree;
        renderTree();
        showReportBtn.disabled = false;
        setStatus('扫描完成 ✓（已恢复上次结果）', 'ok');
        pushLog('✅ 已从服务端恢复上次扫描的目录树，点「查看报告」查看说明。');
        // 若报告已就绪，也恢复入口
        fetch('/api/status?after=0').then(r => r.json()).then(s => {
          if (s.report_ready && s.report_name) {
            const a = document.createElement('a');
            a.id = 'reportLink';
            a.className = 'report-link';
            a.href = '/api/report';
            a.target = '_blank';
            a.textContent = '📄 打开/下载聚焦版 HTML 报告（' + s.report_name + '）';
            logEl.after(a);
          }
        }).catch(() => {});
      }
    })
    .catch(() => {});
}

// 日志改为「最新在上」倒序展示 + 缓冲限流，避免一次性插入数万行 DOM 卡死页面。
function pushLog(line) {
  logLines.push(line);
  if (logLines.length > MAX_LOG_RENDER) logLines = logLines.slice(-MAX_LOG_RENDER);
  renderLog();
}

function appendLogs(newLines, skipped) {
  if (skipped && skipped > 0) {
    logLines.push(`…（扫描日志较多，已折叠更早的 ${skipped} 条，仅展示最近部分）`);
  }
  for (let i = 0; i < newLines.length; i++) logLines.push(newLines[i]);
  if (logLines.length > MAX_LOG_RENDER) logLines = logLines.slice(-MAX_LOG_RENDER);
  renderLog();
}

function renderLog() {
  const frag = document.createDocumentFragment();
  // 倒序：数组末尾是最新日志，从后往前渲染 -> 最新显示在顶部
  for (let i = logLines.length - 1; i >= 0; i--) {
    const t = logLines[i];
    const d = document.createElement('div');
    d.className = 'log-line' + (t.startsWith('…（') ? ' log-note' : '');
    d.textContent = t;
    frag.appendChild(d);
  }
  logEl.replaceChildren(frag);
  logEl.scrollTop = 0; // 最新在顶部，无需滚动即可看到扫描动态
}

function fetchTree() {
  fetch('/api/tree')
    .then(r => r.json())
    .then(d => {
      if (d.ready) {
        treeData = d.tree;
        renderTree();
        showReportBtn.disabled = false;
        pushLog('✅ 扫描完成，可点「查看报告」查看每个文件夹的说明。');
      } else {
        appendLog('⚠ 尚未扫描完成');
      }
    });
}

function renderTree() {
  treeEl.innerHTML = '';
  treeEl.appendChild(renderNode(treeData, true));
  applyFilter();
}

function renderNode(node, isRoot) {
  const wrap = document.createElement('div');
  wrap.className = 'node';

  const row = document.createElement('div');
  row.className = 'row cat-' + node.category;

  const isDir = node.is_dir && !node.is_link;
  const tog = document.createElement('span');
  tog.className = 'tog';
  tog.textContent = isDir ? '▸' : '•';
  row.appendChild(tog);

  const name = document.createElement('span');
  name.className = 'name';
  name.textContent = node.name + (node.is_link ? ' (链接)' : '');
  row.appendChild(name);

  const size = document.createElement('span');
  size.className = 'size';
  size.textContent = node.size_human;
  row.appendChild(size);

  const bar = document.createElement('span');
  bar.className = 'bar';
  bar.style.width = barWidth(node) + 'px';
  row.appendChild(bar);

  const badge = document.createElement('span');
  badge.className = 'badge cat-' + node.category;
  badge.textContent = CAT_LABEL[node.category] || node.category;
  row.appendChild(badge);

  // 「复制地址」按钮：一键复制该文件夹完整路径，便于去资源管理器定位/删除
  const copyBtn = document.createElement('button');
  copyBtn.className = 'copy-btn';
  copyBtn.textContent = '📋 复制地址';
  copyBtn.title = node.path || '';
  copyBtn.onclick = () => copyPath(node.path || '', copyBtn);
  row.appendChild(copyBtn);

  // 「🤖 AI分析」按钮：调用服务端 /api/analyze，分析用途 / 可否删除 / 删除影响
  const aiBtn = document.createElement('button');
  aiBtn.className = 'ai-analyze-btn';
  aiBtn.textContent = '🤖 AI分析';
  aiBtn.title = '用大模型分析：这个文件夹是干什么的、能否删除、删除有何影响';
  aiBtn.onclick = () => analyzeFolder(node, aiBox, aiBtn);
  row.appendChild(aiBtn);

  if (node.description) {
    const desc = document.createElement('div');
    desc.className = 'desc';
    desc.textContent = node.description;
    row.appendChild(desc);
  }
  if (node.advice) {
    const adv = document.createElement('div');
    adv.className = 'advice';
    adv.textContent = '💡 ' + node.advice;
    row.appendChild(adv);
  }
  if (node.error) {
    const e = document.createElement('div');
    e.className = 'err';
    e.textContent = '⚠ 无法访问：' + node.error;
    row.appendChild(e);
  }
  wrap.appendChild(row);

  // AI 说明容器：预分析结果与「🤖 AI分析」点击结果都插入此处，紧跟行下方（位于子节点之上）
  const aiBox = document.createElement('div');
  aiBox.className = 'ai-box';
  wrap.appendChild(aiBox);

  if (node.ai_analyzed) {
    aiBox.appendChild(buildAiBlock(node));
  }

  // 懒加载子节点：初始只渲染首层，展开时再渲染下一层，避免一次性生成数十万 DOM 节点卡死页面
  if (isDir && node.children && node.children.length) {
    const kids = document.createElement('div');
    kids.className = 'children';
    kids.style.display = 'none';
    let loaded = false;
    tog.onclick = () => {
      const willShow = kids.style.display === 'none';
      if (willShow && !loaded) {
        const frag = document.createDocumentFragment();
        node.children.forEach(c => frag.appendChild(renderNode(c, false)));
        kids.appendChild(frag);
        loaded = true;
      }
      kids.style.display = willShow ? 'block' : 'none';
      tog.textContent = willShow ? '▾' : '▸';
    };
    if (isRoot) {
      // 根节点默认展开，但仅渲染直接子级（更深层级仍懒加载）
      node.children.forEach(c => kids.appendChild(renderNode(c, false)));
      loaded = true;
      kids.style.display = 'block';
      tog.textContent = '▾';
    }
    wrap.appendChild(kids);
  }
  return wrap;
}

function barWidth(node) {
  if (!treeData || !treeData.size_bytes) return 2;
  const ratio = node.size_bytes / treeData.size_bytes;
  return Math.max(2, Math.round(ratio * 200));
}

/* ============ 报告视图：文件夹列表 + 逐文件夹说明 ============ */
function renderReport() {
  reportEl.innerHTML = '';
  reportSummaryEl.innerHTML = '';
  if (!treeData) return;

  // 统计各类数量
  let dirCount = 0, totalBytes = treeData.size_bytes, aiCount = 0;
  const catCount = { safe: 0, software_clean: 0, confirm: 0, never: 0, unknown: 0 };
  (function walk(n) {
    if (n.is_dir && !n.is_link) {
      dirCount++;
      catCount[n.category] = (catCount[n.category] || 0) + 1;
      if (n.ai_analyzed) aiCount++;
    }
    (n.children || []).forEach(walk);
  })(treeData);

  const sum = document.createElement('div');
  sum.className = 'summary-card';
  sum.innerHTML =
    `<div><b>扫描路径</b>：${escapeHtml(treeData.path)}</div>` +
    `<div><b>文件夹总数</b>：${dirCount}</div>` +
    `<div><b>占用总大小</b>：${treeData.size_human}</div>` +
    `<div class="summary-cats">` +
      `<span class="badge cat-safe">🟢 可直接删 ${catCount.safe}</span>` +
      `<span class="badge cat-software_clean">🔵 软件内清 ${catCount.software_clean}</span>` +
      `<span class="badge cat-confirm">🟡 需确认 ${catCount.confirm}</span>` +
      `<span class="badge cat-never">🔴 禁止删 ${catCount.never}</span>` +
      `<span class="badge cat-unknown">⚪ 未收录 ${catCount.unknown}</span>` +
      (aiCount ? `<span class="badge cat-ai">🤖 AI 识别 ${aiCount}</span>` : '') +
    `</div>`;
  reportSummaryEl.appendChild(sum);

  // 递归渲染文件夹列表（仅目录，缩进表示层级）
  const list = document.createElement('div');
  list.className = 'report-list';
  reportCount = 0;
  (treeData.children || []).forEach(c => renderReportNode(c, 0, list));
  reportEl.appendChild(list);
  if (reportCount >= REPORT_MAX) {
    const note = document.createElement('div');
    note.className = 'report-note';
    note.textContent = `为浏览器性能，网页版仅展示前 ${REPORT_MAX} 个文件夹；完整报告（含全部说明）请使用导出的 HTML 文件。`;
    reportEl.appendChild(note);
  }
}

function renderReportNode(node, depth, container) {
  if (reportCount >= REPORT_MAX) return;        // 超过上限停止渲染，避免 DOM 过大卡死
  if (!(node.is_dir && !node.is_link)) return;  // 报告只列文件夹
  const item = document.createElement('div');
  item.className = 'report-item cat-' + node.category;
  item.style.marginLeft = (depth * 18) + 'px';

  const head = document.createElement('div');
  head.className = 'report-head';
  head.innerHTML =
    `<span class="report-icon">📁</span>` +
    `<span class="report-name">${escapeHtml(node.name)}</span>` +
    `<span class="report-size">${node.size_human}</span>` +
    `<span class="badge cat-${node.category}">${CAT_ICON[node.category] || '⚪'} ${CAT_LABEL[node.category] || node.category}</span>`;
  item.appendChild(head);

  // 「复制地址」按钮：一键复制该文件夹完整路径，便于去资源管理器定位/删除
  const copyBtn = document.createElement('button');
  copyBtn.className = 'copy-btn';
  copyBtn.textContent = '📋 复制地址';
  copyBtn.title = node.path || '';
  copyBtn.onclick = () => copyPath(node.path || '', copyBtn);
  head.appendChild(copyBtn);

  // 「🤖 AI分析」按钮：调用服务端 /api/analyze，分析该文件夹的用途 / 可否删除 / 删除影响
  const aiBtn = document.createElement('button');
  aiBtn.className = 'ai-analyze-btn';
  aiBtn.textContent = '🤖 AI分析';
  aiBtn.title = '用大模型分析：这个文件夹是干什么的、能否删除、删除有何影响';
  aiBtn.onclick = () => analyzeFolder(node, item, aiBtn);
  head.appendChild(aiBtn);

  const desc = document.createElement('div');
  desc.className = 'report-desc';
  if (node.description) {
    desc.innerHTML = `<b>是什么：</b>${escapeHtml(node.description)}`;
  } else {
    desc.innerHTML = `<b>是什么：</b><span class="muted">（暂未识别——规则库与 AI 均未覆盖，建议保持不动，确需清理请先确认内容）</span>`;
  }
  item.appendChild(desc);

  if (node.advice) {
    const adv = document.createElement('div');
    adv.className = 'report-advice';
    adv.innerHTML = `<b>清理建议：</b>${escapeHtml(node.advice)}`;
    item.appendChild(adv);
  }
  if (node.error) {
    const e = document.createElement('div');
    e.className = 'err';
    e.textContent = '⚠ 无法访问：' + node.error;
    item.appendChild(e);
  }
  if (node.ai_analyzed) {
    item.classList.add('ai');
    item.dataset.ai = '1';
    item.appendChild(buildAiBlock(node));
  }
  container.appendChild(item);
  reportCount++;

  (node.children || []).forEach(c => renderReportNode(c, depth + 1, container));
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// 一键复制文件夹完整路径（Clipboard API，失败回退 textarea+execCommand）
function copyPath(text, btn) {
  const done = () => {
    const t = btn.textContent;
    btn.textContent = '✅ 已复制';
    setTimeout(() => { btn.textContent = t; }, 1200);
  };
  const fallback = () => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch (e) {}
    document.body.removeChild(ta);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, fallback);
  } else {
    fallback();
  }
}

searchInput.oninput = applyFilter;
filterSel.onchange = applyFilter;

function applyFilter() {
  const q = searchInput.value.trim().toLowerCase();
  const f = filterSel.value;

  // 「🔍 AI 识别」专属筛选：只看被 AI 识别的大文件夹
  if (f === 'ai') {
    treeEl.querySelectorAll('.node').forEach(n => {
      const isAi = !!n.querySelector('.badge.cat-ai');
      const name = (n.querySelector('.name')?.textContent || '').toLowerCase();
      n.style.display = (isAi && (!q || name.includes(q))) ? 'block' : 'none';
    });
    reportEl.querySelectorAll('.report-item').forEach(n => {
      const isAi = n.classList.contains('ai');
      const name = (n.querySelector('.report-name')?.textContent || '').toLowerCase();
      n.style.display = (isAi && (!q || name.includes(q))) ? 'block' : 'none';
    });
    return;
  }

  // 目录树筛选
  treeEl.querySelectorAll('.node').forEach(n => {
    const name = (n.querySelector('.name')?.textContent || '').toLowerCase();
    const catOk = f === 'all' || n.querySelector('.badge')?.className.includes('cat-' + f);
    let show = true;
    if (q && !name.includes(q)) show = false;
    if (!catOk) show = false;
    n.style.display = show ? 'block' : 'none';
  });
  // 报告筛选
  reportEl.querySelectorAll('.report-item').forEach(n => {
    const name = (n.querySelector('.report-name')?.textContent || '').toLowerCase();
    const catOk = f === 'all' || n.className.includes('cat-' + f);
    let show = true;
    if (q && !name.includes(q)) show = false;
    if (!catOk) show = false;
    n.style.display = show ? 'block' : 'none';
  });
}

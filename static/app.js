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
// —— 入口 Key 校验弹窗元素 ——
const keyGate = document.getElementById('keyGate');
const appRoot = document.getElementById('appRoot');
const keyInput = document.getElementById('keyInput');
const keySubmit = document.getElementById('keySubmit');
const keySkip = document.getElementById('keySkip');
const keyError = document.getElementById('keyError');
const keyTesting = document.getElementById('keyTesting');
let treeData = null;
let logOffset = 0;
let pollTimer = null;
let logLines = [];          // 前端日志缓冲（仅用于渲染，最多保留最近 MAX_LOG_RENDER 条）
const MAX_LOG_RENDER = 1000;
let reportCount = 0;        // 报告渲染计数器（用于限流）
const REPORT_MAX = 5000;

/* ============ 入口 Key 校验：无可用 Key 先弹窗，测试通过才进入功能界面 ============ */
function showKeyGate() {
  keyGate.style.display = 'flex';
  appRoot.style.display = 'none';
  keyError.style.display = 'none';
  keyInput.focus();
}

function enterApp() {
  keyGate.style.display = 'none';
  appRoot.style.display = 'block';
  recoverTree();   // 进入后恢复上次扫描结果（如有）
}

function showKeyError(msg) {
  keyError.textContent = msg;
  keyError.style.display = 'block';
  keyTesting.style.display = 'none';
  keySubmit.disabled = false;
  keySkip.disabled = false;
}

function submitKey() {
  const key = keyInput.value.trim();
  if (!key) { showKeyError('请先填入 DeepSeek API Key'); return; }
  keyError.style.display = 'none';
  keyTesting.style.display = 'block';
  keySubmit.disabled = true;
  keySkip.disabled = true;
  fetch('/api/set_key', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key })
  })
    .then(r => r.json().then(d => ({ status: r.status, d })))
    .then(({ status, d }) => {
      if (d && d.ok) { enterApp(); return; }
      showKeyError(d && d.error ? d.error : ('测试失败（HTTP ' + status + '）'));
    })
    .catch(err => {
      showKeyError('请求出错：' + err);
    });
}

keySubmit.onclick = submitKey;
keyInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitKey(); });
keySkip.onclick = enterApp;   // 跳过：只用基础扫描（AI 按钮点击时后端会提示未启用）

function checkKeyGate() {
  fetch('/api/key_status')
    .then(r => r.json())
    .then(d => {
      if (d && d.has_key) {
        enterApp();          // 服务端已有可用 Key，直接进入
      } else {
        showKeyGate();       // 无 Key，弹窗
      }
    })
    .catch(() => {
      // 接口异常时仍可放行（避免卡死在弹窗），但默认给弹窗更稳妥——这里选择直接进，扫描不依赖 Key
      enterApp();
    });
}


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

// 页面加载：先校验入口 Key（无可用 Key 弹窗，测试通过才进入功能界面并恢复上次结果）
checkKeyGate();

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

  // 「打开文件夹」按钮：调用服务端 /api/open，在本地资源管理器直接打开该路径
  const copyBtn = document.createElement('button');
  copyBtn.className = 'open-btn';
  copyBtn.textContent = '📂 打开文件夹';
  copyBtn.title = '在本机资源管理器中打开此文件夹';
  copyBtn.onclick = () => openFolder(node.path || '', copyBtn);
  row.appendChild(copyBtn);

  // 「🤖 AI分析」按钮：调用服务端 /api/analyze，分析用途 / 可否删除 / 删除影响
  const aiBtn = document.createElement('button');
  aiBtn.className = 'ai-analyze-btn';
  aiBtn.textContent = '🤖 AI分析';
  aiBtn.title = '用大模型分析：这个文件夹是干什么的、能否删除、删除有何影响';
  aiBtn.onclick = () => analyzeFolder(node, aiBox, aiBtn);
  row.appendChild(aiBtn);

  // 「🗑 删除」按钮：经服务端 /api/delete（默认进回收站）删除该文件夹，删后刷新视图
  const delBtn = document.createElement('button');
  delBtn.className = 'delete-btn';
  delBtn.textContent = '🗑 删除';
  delBtn.title = '删除此文件夹（默认进回收站，可在回收站恢复）';
  delBtn.onclick = () => deleteFolder(node, wrap);
  row.appendChild(delBtn);

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

  // 「打开文件夹」按钮：调用服务端 /api/open，在本地资源管理器直接打开该路径
  const copyBtn = document.createElement('button');
  copyBtn.className = 'open-btn';
  copyBtn.textContent = '📂 打开文件夹';
  copyBtn.title = '在本机资源管理器中打开此文件夹';
  copyBtn.onclick = () => openFolder(node.path || '', copyBtn);
  head.appendChild(copyBtn);

  // 「🤖 AI分析」按钮：调用服务端 /api/analyze，分析该文件夹的用途 / 可否删除 / 删除影响
  const aiBtn = document.createElement('button');
  aiBtn.className = 'ai-analyze-btn';
  aiBtn.textContent = '🤖 AI分析';
  aiBtn.title = '用大模型分析：这个文件夹是干什么的、能否删除、删除有何影响';
  aiBtn.onclick = () => analyzeFolder(node, item, aiBtn);
  head.appendChild(aiBtn);

  // 「🗑 删除」按钮：经服务端 /api/delete（默认进回收站）删除该文件夹，删后刷新视图
  const delBtn = document.createElement('button');
  delBtn.className = 'delete-btn';
  delBtn.textContent = '🗑 删除';
  delBtn.title = '删除此文件夹（默认进回收站，可在回收站恢复）';
  delBtn.onclick = () => deleteFolder(node, item);
  head.appendChild(delBtn);

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

// 「打开文件夹」：调用服务端 /api/open，在本机资源管理器中直接打开该路径
function openFolder(path, btn) {
  if (!path) return;
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⏳ 打开中…';
  fetch('/api/open', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path })
  })
    .then(r => r.json().then(j => ({ ok: r.ok, j })))
    .then(({ ok, j }) => {
      if (ok && j.ok) {
        btn.textContent = '✅ 已打开';
      } else {
        alert('打开失败：' + (j.error || '未知错误'));
        btn.textContent = orig;
      }
    })
    .catch(err => {
      alert('打开请求出错：' + err);
      btn.textContent = orig;
    })
    .finally(() => {
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 1500);
    });
}

// 删除文件夹：二次确认（防误删）→ 调服务端 /api/delete（默认进回收站）→ 成功后从视图移除并刷新
function deleteFolder(node, itemEl) {
  const path = node.path || '';
  if (!path) return;
  const ok = confirm(
    '⚠️ 即将删除文件夹：\n' + path + '\n\n' +
    '· 默认进入「回收站」，可在回收站恢复（若服务端无回收站支持则永久删除）。\n' +
    '· 系统/关键目录已被保护，无法删。\n' +
    '· 确认删除？'
  );
  if (!ok) return;
  const delBtn = itemEl.querySelector('.delete-btn');
  if (delBtn) { delBtn.disabled = true; delBtn.textContent = '⏳ 删除中…'; }
  fetch('/api/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path })
  })
    .then(r => {
      if (!r.headers.get('content-type') || !r.headers.get('content-type').includes('application/json')) {
        return r.text().then(t => ({ ok: false, d: { error: '后端返回非 JSON（可能 /api/delete 不存在），请确认已重启最新版 app.py。响应前 200 字：' + t.slice(0, 200) } }));
      }
      return r.json().then(d => ({ ok: r.ok, d }));
    })
    .then(({ ok, d }) => {
      if (!ok || !d.ok) {
        alert('删除失败：' + (d && d.error ? d.error : '未知错误'));
        if (delBtn) { delBtn.disabled = false; delBtn.textContent = '🗑 删除'; }
        return;
      }
      // 从前端内存树移除该节点
      removeNodeFromTree(treeData, path);
      // 从 DOM 移除该节点所在的整块（目录树节点 wrap，或报告 item）
      itemEl.remove();
      pushLog('🗑 已删除：' + path + (d.method === 'permanent' ? '（永久删除）' : '（已进回收站）'));
      setStatus('已删除 1 项', 'ok');
    })
    .catch(err => {
      alert('删除请求出错：' + err);
      if (delBtn) { delBtn.disabled = false; delBtn.textContent = '🗑 删除'; }
    });
}

// 从前端内存树（treeData）递归移除指定路径节点，供后续刷新/报告一致
function removeNodeFromTree(node, path) {
  if (!node || !node.children) return false;
  const target = path.replace('/', '\\').toLowerCase();
  for (let i = 0; i < node.children.length; i++) {
    const c = node.children[i];
    if (c.path.replace('/', '\\').toLowerCase() === target) {
      node.children.splice(i, 1);
      return true;
    }
    if (removeNodeFromTree(c, path)) return true;
  }
  return false;
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

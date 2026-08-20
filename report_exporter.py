"""生成一个自包含的交互式 HTML 报告文件（内联 CSS+JS+数据），
可在任意浏览器直接打开，无需后端。用于网页版/小程序等无法访问
本地 localhost 的场景交付扫描结果。
"""
import json
import html
import os


REPORT_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0; font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  background: #f5f6f8; color: #1f2329;
}
.wrap { max-width: 980px; margin: 0 auto; padding: 16px 20px 60px; }
h1 { font-size: 20px; margin: 8px 0 4px; }
.sub { color: #8a8f99; font-size: 13px; margin-bottom: 14px; }
.report-summary { margin-bottom: 16px; }
.summary-card {
  background: #fafbfc; border: 1px solid #eef0f3; border-radius: 8px;
  padding: 12px 14px; line-height: 1.9; font-size: 13px;
}
.summary-cats { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.badge {
  font-size: 12px; padding: 2px 8px; border-radius: 10px; color: #fff; white-space: nowrap;
}
.badge.cat-safe { background: #2ba471; }
.badge.cat-software_clean { background: #3370ff; }
.badge.cat-confirm { background: #d4860b; }
.badge.cat-never { background: #d93026; }
.badge.cat-unknown { background: #86909c; }
.report-list { padding: 0; }
.report-item {
  padding: 10px 12px; border: 1px solid #eef0f3; border-left: 3px solid #c9cdd4;
  border-radius: 6px; margin-bottom: 8px; background: #fff;
}
.report-item.cat-safe { border-left-color: #2ba471; background: #f7fcf9; }
.report-item.cat-software_clean { border-left-color: #3370ff; background: #f7f9ff; }
.report-item.cat-confirm { border-left-color: #d4860b; background: #fffcf5; }
.report-item.cat-never { border-left-color: #d93026; background: #fff7f7; }
.report-item.cat-unknown { border-left-color: #86909c; background: #fafafa; }
.report-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.report-icon { font-size: 15px; }
.report-name { font-weight: 600; word-break: break-all; }
.report-size { color: #4e5969; font-variant-numeric: tabular-nums; min-width: 76px; }
.report-desc { margin-top: 6px; color: #1f2329; font-size: 13px; line-height: 1.6; }
.report-advice { margin-top: 4px; color: #3370ff; font-size: 13px; line-height: 1.6; }
.muted { color: #a9aeb8; font-weight: 400; }
.err { margin-top: 4px; color: #d93026; font-size: 12px; }
.badge.cat-ai { background: #7c3aed; }
.badge.lvl-safe { background: #2ba471; }
.badge.lvl-caution { background: #d4860b; }
.badge.lvl-never { background: #d93026; }
.ai-block { margin: 6px 0 2px; padding: 6px 10px; background: #f6f3ff; border: 1px solid #e4dcff; border-radius: 6px; font-size: 13px; }
.ai-block .badge { margin-right: 6px; }
.ai-block .muted { margin-left: 4px; }
.ai-line { margin-top: 3px; line-height: 1.6; color: #1f2329; }
.ai-line b { color: #4e5969; }
.ai-summary { margin-top: 5px; padding: 5px 8px; background: #fff; border: 1px solid #e4dcff; border-radius: 5px; line-height: 1.6; color: #1f2329; font-size: 13px; }
.ai-summary b { color: #5b21b6; }
.report-item.ai { border-left-color: #7c3aed; background: #faf8ff; }
.controls { display: flex; gap: 8px; flex-wrap: wrap; margin: 4px 0 14px; }
.controls input, .controls select {
  padding: 7px 10px; border: 1px solid #d0d3d9; border-radius: 6px; font-size: 13px;
}
.controls input { flex: 1; min-width: 200px; }
.copy-btn {
  margin-left: auto; border: 1px solid #d0d3d9; background: #fff; color: #3370ff;
  font-size: 12px; padding: 3px 9px; border-radius: 6px; cursor: pointer; white-space: nowrap;
}
.copy-btn:hover { background: #f0f5ff; }
.copy-btn.sm { margin-left: 6px; padding: 1px 6px; font-size: 11px; }
.ai-analyze-btn {
  margin-left: 6px; border: 1px solid #d0d3d9; background: #f6f3ff; color: #7c3aed;
  font-size: 12px; padding: 3px 9px; border-radius: 6px; cursor: pointer; white-space: nowrap;
}
.ai-analyze-btn:hover { background: #efeaff; }
.ai-analyze-btn:disabled { opacity: .6; cursor: progress; }
.ai-analyze-btn.sm { margin-left: 4px; padding: 1px 6px; font-size: 11px; }
.ai-result { margin-top: 6px; }
.ds-key { flex: 1.3; min-width: 220px; }
.ds-hint { font-size: 12px; color: #8a8f99; margin: 4px 0 14px; line-height: 1.6; }
.ds-hint b { color: #7c3aed; }
"""

REPORT_JS = """
const CAT_LABEL = {safe:'可直接删', software_clean:'软件内清', confirm:'需确认', never:'禁止删', unknown:'未收录', ai:'AI 识别'};
const CAT_ICON = {safe:'🟢', software_clean:'🔵', confirm:'🟡', never:'🔴', unknown:'⚪', ai:'🤖'};
const LV_LABEL = {safe:'🟢 可删除', caution:'🟡 谨慎', never:'🔴 别删'};
const CONF_LABEL = {high:'高', medium:'中', low:'低'};
function escapeHtml(s){
  return String(s==null?'':s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;');
}
function aiBlock(node){
  const lv = node.level||'caution';
  const summary = node.summary||node.purpose||node.description||'';
  return '<div class="ai-block">'+
    '<span class="badge cat-ai">🤖 AI 识别</span>'+
    '<span class="badge lvl-'+lv+'">'+(LV_LABEL[lv]||'谨慎')+'</span>'+
    (node.confidence?'<span class="muted">把握：'+(CONF_LABEL[node.confidence]||node.confidence)+'</span>':'')+
    (summary?'<div class="ai-summary"><b>📝 这是什么：</b>'+escapeHtml(summary)+'</div>':'')+
    (node.software?'<div class="ai-line"><b>📦 软件：</b>'+escapeHtml(node.software)+'</div>':'')+
    (node.deletable?'<div class="ai-line"><b>🗑 能否删除：</b>'+escapeHtml(node.deletable)+'</div>':'')+
    '</div>';
}
function copyPath(text, btn){
  var done = function(){ var t=btn.textContent; btn.textContent='✅ 已复制'; setTimeout(function(){btn.textContent=t;},1200); };
  var fb = function(){ var ta=document.createElement('textarea'); ta.value=text; ta.style.position='fixed'; ta.style.opacity='0'; document.body.appendChild(ta); ta.select(); try{document.execCommand('copy'); done();}catch(e){} document.body.removeChild(ta); };
  if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(text).then(done, fb); } else { fb(); }
}
document.addEventListener('click', function(e){
  var btn = e.target && e.target.closest ? e.target.closest('.copy-btn') : null;
  if(!btn) return;
  var item = btn.closest ? btn.closest('.report-item') : null;
  var path = btn.dataset.path || (item && item.dataset.path);
  if(path) copyPath(path, btn);
});
function aiResultBlock(r){
  r = r||{};
  var lv = r.level||'caution';
  return '<div class="ai-block">'+
    '<span class="badge cat-ai">🤖 AI 分析</span>'+
    '<span class="badge lvl-'+lv+'">'+(LV_LABEL[lv]||'谨慎')+'</span>'+
    (r.confidence?'<span class="muted">把握：'+(CONF_LABEL[r.confidence]||r.confidence)+'</span>':'')+
    (r.summary?'<div class="ai-line"><b>📝 是什么：</b>'+esc(r.summary)+'</div>':'')+
    (r.deletable?'<div class="ai-line"><b>🗑 能否删除：</b>'+esc(r.deletable)+'</div>':'')+
    (r.impact?'<div class="ai-line"><b>⚠ 删除影响：</b>'+esc(r.impact)+'</div>':'')+
    '</div>';
}
// 浏览器端直接调用 DeepSeek（报告为自包含文件，无后端）。Key 仅存本机 localStorage。
function aiAnalyze(path, name, size, container){
  if(!container || container.querySelector('.ai-result')) return;
  var btn = container.querySelector('.ai-analyze-btn');
  if(btn){ btn.disabled = true; btn.textContent = '⏳ 分析中…'; }
  var keyEl = document.getElementById('dsKey');
  var key = (keyEl && keyEl.value.trim()) || (localStorage.getItem('ds_key')||'');
  if(!key){
    alert('请先在页面顶部输入 DeepSeek API Key（仅保存在你本机浏览器，用于调用 AI 分析）。');
    if(keyEl) keyEl.focus();
    if(btn){ btn.disabled=false; btn.textContent='🤖 AI分析'; }
    return;
  }
  var prompt = '下面文件地址中，这个文件夹是干什么的？' + path + ' （大小约 ' + (size||'未知') + '） 请判断：1) summary：一句话说明这个文件夹是做什么用的、里面一般存放什么内容；2) level：删除它的风险——safe=可放心删除（多为缓存/临时/可重建），caution=可删但要先备份或退出对应软件，never=不建议/禁止删除（删了会导致软件或系统异常）；3) deletable：一句话给「能不能删除」的具体结论；4) impact：如果删除，会影响什么（如：某软件无法启动、某游戏进度丢失、系统功能异常等），不确定写「影响未知，建议先备份」；5) confidence：你判断的把握 high / medium / low。 只输出严格 JSON：{"summary":"","level":"safe|caution|never","deletable":"","impact":"","confidence":"high|medium|low"}';
  fetch('https://api.deepseek.com/chat/completions', {
    method:'POST',
    headers:{'Content-Type':'application/json','Authorization':'Bearer '+key},
    body: JSON.stringify({model:'deepseek-chat', messages:[
      {role:'system', content:'你是 Windows 磁盘清理助手，只输出严格 JSON，不要多余文字。'},
      {role:'user', content: prompt}
    ], temperature:0.1})
  })
  .then(function(r){ return r.json().then(function(d){ return {ok:r.ok, d:d}; }); })
  .then(function(o){
    if(btn){ btn.disabled=false; btn.textContent='🤖 AI分析'; }
    if(!o.ok || o.d.error){ alert('分析失败：' + (o.d && o.d.error ? o.d.error.message : '未知错误')); return; }
    var text = (o.d.choices && o.d.choices[0]) ? (o.d.choices[0].message.content || '') : '';
    var m = text.indexOf('{'), e = text.lastIndexOf('}');
    var r = {};
    if(m>=0 && e>m){ try{ r = JSON.parse(text.slice(m, e+1)); }catch(_){} }
    if(!r || !r.summary){ alert('分析返回格式异常，请重试。'); return; }
    var box = document.createElement('div');
    box.className = 'ai-result';
    box.innerHTML = aiResultBlock(r);
    container.appendChild(box);
  })
  .catch(function(err){
    if(btn){ btn.disabled=false; btn.textContent='🤖 AI分析'; }
    alert('分析请求出错：' + err);
  });
}
function renderReport(){
  const root = DATA;
  let dirCount = 0, aiCount = 0;
  const catCount = {safe:0, software_clean:0, confirm:0, never:0, unknown:0};
  (function walk(n){
    if(n.is_dir && !n.is_link){ dirCount++; catCount[n.category]=(catCount[n.category]||0)+1; if(n.ai_analyzed)aiCount++; }
    (n.children||[]).forEach(walk);
  })(root);
  const sum = document.getElementById('summary');
  sum.innerHTML =
    '<div><b>扫描路径</b>：'+escapeHtml(root.path)+'</div>'+
    '<div><b>文件夹总数</b>：'+dirCount+'</div>'+
    '<div><b>占用总大小</b>：'+root.size_human+'</div>'+
    '<div class="summary-cats">'+
      '<span class="badge cat-safe">🟢 可直接删 '+catCount.safe+'</span>'+
      '<span class="badge cat-software_clean">🔵 软件内清 '+catCount.software_clean+'</span>'+
      '<span class="badge cat-confirm">🟡 需确认 '+catCount.confirm+'</span>'+
      '<span class="badge cat-never">🔴 禁止删 '+catCount.never+'</span>'+
      '<span class="badge cat-unknown">⚪ 未收录 '+catCount.unknown+'</span>'+
      (aiCount?'<span class="badge cat-ai">🤖 AI 识别 '+aiCount+'</span>':'')+
    '</div>';
  const list = document.getElementById('list');
  list.innerHTML = '';
  (root.children||[]).forEach(c => renderReportNode(c, 0, list));
  applyFilter();
}
function renderReportNode(node, depth, container){
  if(!(node.is_dir && !node.is_link)) return;
  const item = document.createElement('div');
  item.className = 'report-item cat-'+node.category;
  if(node.ai_analyzed){ item.className += ' ai'; item.dataset.ai='1'; }
  item.style.marginLeft = (depth*18)+'px';
  item.dataset.name = (node.name||'').toLowerCase();
  item.dataset.cat = node.category;
  item.dataset.path = node.path;
  const head = document.createElement('div');
  head.className = 'report-head';
  head.innerHTML =
    '<span class="report-icon">📁</span>'+
    '<span class="report-name">'+escapeHtml(node.name)+'</span>'+
    '<span class="report-size">'+node.size_human+'</span>'+
    '<span class="badge cat-'+node.category+'">'+(CAT_ICON[node.category]||'⚪')+' '+(CAT_LABEL[node.category]||node.category)+'</span>';
  item.appendChild(head);
  const cp = document.createElement('button');
  cp.className = 'copy-btn';
  cp.textContent = '📋 复制地址';
  head.appendChild(cp);
  const ab = document.createElement('button');
  ab.className = 'ai-analyze-btn';
  ab.textContent = '🤖 AI分析';
  ab.title = '用大模型分析：这个文件夹是干什么的、能否删除、删除有何影响';
  ab.dataset.path = node.path || '';
  ab.dataset.name = node.name || '';
  ab.dataset.size = node.size_human || '';
  head.appendChild(ab);
  const desc = document.createElement('div');
  desc.className = 'report-desc';
  if(node.description){
    desc.innerHTML = '<b>是什么：</b>'+escapeHtml(node.description);
  } else {
    desc.innerHTML = '<b>是什么：</b><span class="muted">（暂未识别——规则库与 AI 均未覆盖，建议保持不动，确需清理请先确认内容）</span>';
  }
  item.appendChild(desc);
  if(node.advice){
    const adv = document.createElement('div');
    adv.className = 'report-advice';
    adv.innerHTML = '<b>清理建议：</b>'+escapeHtml(node.advice);
    item.appendChild(adv);
  }
  if(node.error){
    const e = document.createElement('div');
    e.className = 'err';
    e.textContent = '⚠ 无法访问：'+node.error;
    item.appendChild(e);
  }
  if(node.ai_analyzed){
    const ai = document.createElement('div');
    ai.innerHTML = aiBlock(node);
    item.appendChild(ai.firstChild);
  }
  container.appendChild(item);
  (node.children||[]).forEach(c => renderReportNode(c, depth+1, container));
}
function applyFilter(){
  const q = (document.getElementById('q').value||'').trim().toLowerCase();
  const f = document.getElementById('f').value;
  if(f==='ai'){
    document.querySelectorAll('.report-item').forEach(n=>{
      const nameOk = !q || (n.dataset.name||'').includes(q);
      n.style.display = (n.dataset.ai==='1' && nameOk) ? 'block' : 'none';
    });
    return;
  }
  document.querySelectorAll('.report-item').forEach(n=>{
    const nameOk = !q || (n.dataset.name||'').includes(q);
    const catOk = f==='all' || n.dataset.cat===f;
    n.style.display = (nameOk && catOk) ? 'block' : 'none';
  });
}
window.addEventListener('DOMContentLoaded', function(){
  renderReport();
  document.getElementById('q').addEventListener('input', applyFilter);
  document.getElementById('f').addEventListener('change', applyFilter);
  var ke = document.getElementById('dsKey');
  if(ke){ var sv = localStorage.getItem('ds_key')||''; ke.value = sv; ke.addEventListener('input', function(){ localStorage.setItem('ds_key', ke.value.trim()); }); }
});
"""


def prune_files(node):
    """只保留目录节点（去掉文件叶子），大幅缩减体积。
    目录本身的大小已在扫描时算好（含其下所有文件），剪掉文件不影响大小统计。
    原地修改并返回节点。"""
    if not (node.get('is_dir') and not node.get('is_link')):
        return None
    kids = node.get('children') or []
    node['children'] = [c for c in (prune_files(c) for c in kids) if c is not None]
    return node


def export_report_html(tree, out_path):
    """把目录树渲染成自包含 HTML 报告文件。"""
    tree = prune_files(tree)  # 去掉文件叶子，报告只需文件夹列表
    data_json = html.escape(json.dumps(tree, ensure_ascii=False))
    # 注意：上面转义了引号，JS 里用 JSON.parse 还原
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>C 盘文件夹扫描报告</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>C 盘文件夹扫描报告</h1>
  <div class="sub">每个文件夹的用途与清理建议（工具只读扫描，不删除任何文件）</div>
  <div class="controls">
    <input id="q" placeholder="搜索文件夹名…">
    <select id="f">
      <option value="all">全部分类</option>
      <option value="ai">🤖 AI 识别（大文件夹）</option>
      <option value="safe">🟢 可直接删</option>
      <option value="software_clean">🔵 软件内清</option>
      <option value="confirm">🟡 需确认</option>
      <option value="never">🔴 禁止删</option>
      <option value="unknown">⚪ 未收录</option>
    </select>
    <input id="dsKey" class="ds-key" placeholder="DeepSeek API Key（可选，用于逐文件夹 AI 分析）">
  </div>
  <div class="ds-hint">点每个文件夹的「🤖 AI分析」可调用 DeepSeek 分析其用途、能否删除及删除影响。Key 仅保存在你本机浏览器（localStorage），不会上传给他人。</div>
  <div class="report-summary"><div id="summary" class="summary-card"></div></div>
  <div id="list" class="report-list"></div>
</div>
<script>
const DATA = JSON.parse("{data_json}");
{REPORT_JS}
</script>
</body>
</html>
"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(page)
    return out_path


def build_focused_payload(tree, top_n=500):
    """只抽取「最大的 N 个」+「所有有说明的文件夹」+「未收录大文件夹 AI 识别」，避开十几万未识别噪声。"""
    total_dirs = 0
    cat_counts = {}
    top = []
    described = []
    big_unknown = []   # 未收录且被 AI 识别（>2GB）的大文件夹

    def walk(n):
        nonlocal total_dirs
        if not (n.get('is_dir') and not n.get('is_link')):
            return
        total_dirs += 1
        c = n.get('category', 'unknown')
        cat_counts[c] = cat_counts.get(c, 0) + 1
        size = n.get('size_bytes', 0)
        rec = {
            'n': n.get('name', ''),
            'p': n.get('path', ''),
            's': n.get('size_human', ''),
            'c': c,
            'd': n.get('description', '') or '',
            'a': n.get('advice', '') or '',
        }
        top.append((size, rec))
        if rec['d']:
            described.append(rec)
        if n.get('ai_analyzed') and n.get('size_bytes', 0) >= 2 * 1024 ** 3:
            big_unknown.append({
                'n': n.get('name', ''),
                'p': n.get('path', ''),
                's': n.get('size_human', ''),
                'summary': n.get('summary') or n.get('purpose') or n.get('description') or '',
                'software': n.get('software', '') or '',
                'purpose': n.get('purpose', '') or '',
                'deletable': n.get('deletable', '') or '',
                'level': n.get('level', 'caution') or 'caution',
                'confidence': n.get('confidence', 'low') or 'low',
            })
        for k in n.get('children', []):
            walk(k)

    walk(tree)
    top.sort(key=lambda x: x[0], reverse=True)
    top = [r for _, r in top[:top_n]]
    # 已识别列表按大小排序，方便看重点
    described.sort(key=lambda r: _size_of(r['s']), reverse=True)
    big_unknown.sort(key=lambda r: _size_of(r['s']), reverse=True)
    return {
        'meta': {
            'path': tree.get('path', ''),
            'total_size': tree.get('size_human', ''),
            'total_dirs': total_dirs,
            'cat_counts': cat_counts,
            'top_n': top_n,
        },
        'top': top,
        'described': described,
        'big_unknown': big_unknown,
    }


def _size_of(h):
    try:
        num, unit = h.split()
        mult = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
        return float(num) * mult.get(unit, 1)
    except Exception:
        return 0


FOCUSED_CSS = REPORT_CSS + """
.section-title { font-size: 15px; font-weight: 600; margin: 18px 0 8px; }
.sec-top table { width: 100%; border-collapse: collapse; font-size: 13px; }
.sec-top th, .sec-top td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eef0f3; vertical-align: top; }
.sec-top th { color: #8a8f99; font-weight: 500; }
.sec-top td.sz { white-space: nowrap; font-variant-numeric: tabular-nums; color: #4e5969; }
.sec-top tr:hover { background: #fafbfc; }
"""

FOCUSED_JS = """
const CAT_LABEL = {safe:'可直接删', software_clean:'软件内清', confirm:'需确认', never:'禁止删', unknown:'未收录', ai:'AI 识别'};
const CAT_ICON = {safe:'🟢', software_clean:'🔵', confirm:'🟡', never:'🔴', unknown:'⚪', ai:'🤖'};
const LV_LABEL = {safe:'🟢 可删除', caution:'🟡 谨慎', never:'🔴 别删'};
const CONF_LABEL = {high:'高', medium:'中', low:'低'};
function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function badge(c){ return '<span class="badge cat-'+c+'">'+(CAT_ICON[c]||'⚪')+' '+(CAT_LABEL[c]||c)+'</span>'; }
function lvBadge(l){ l=l||'caution'; return '<span class="badge lvl-'+l+'">'+(LV_LABEL[l]||'谨慎')+'</span>'; }
function renderSummary(){
  const m = DATA.meta;
  const cc = m.cat_counts||{};
  const cats = ['safe','software_clean','confirm','never','unknown'].map(k=>
    '<span class="badge cat-'+k+'">'+(CAT_ICON[k]||'⚪')+' '+(CAT_LABEL[k]||k)+' '+(cc[k]||0)+'</span>').join('');
  const aiCnt = (DATA.big_unknown&&DATA.big_unknown.length)||0;
  document.getElementById('summary').innerHTML =
    '<div><b>扫描路径</b>：'+esc(m.path)+'</div>'+
    '<div><b>文件夹总数</b>：'+m.total_dirs+'</div>'+
    '<div><b>占用总大小</b>：'+m.total_size+'</div>'+
    '<div><b>说明</b>：仅列出最大的 '+m.top_n+' 个文件夹与全部「已识别/有说明」的文件夹；其余 '+ (m.total_dirs - DATA.described.length) +' 个多为 node_modules/.git 等未识别目录，未平铺以避免报告过大。</div>'+
    '<div class="summary-cats">'+cats+(aiCnt?'<span class="badge cat-ai">🤖 AI 识别 '+aiCnt+'</span>':'')+'</div>';
}
function renderTop(){
  const rows = DATA.top.map((r,i)=>
    '<tr><td>'+(i+1)+'</td><td class="sz">'+r.s+'</td><td>'+esc(r.n)+
    (r.d?' <span class="muted">'+esc(r.d)+'</span>':'')+'</td><td>'+badge(r.c)+'</td>'+
    '<td class="muted" title="'+esc(r.p)+'">'+esc(r.p)+' <button class="copy-btn sm" data-path="'+esc(r.p)+'">📋</button><button class="ai-analyze-btn sm" data-path="'+esc(r.p)+'" data-name="'+esc(r.n)+'" data-size="'+esc(r.s)+'">🤖</button></td></tr>').join('');
  document.getElementById('topBody').innerHTML = rows;
}
function renderDescribed(){
  const list = document.getElementById('descList');
  list.innerHTML = '';
  DATA.described.forEach(r=>{
    const item = document.createElement('div');
    item.className = 'report-item cat-'+r.c;
    item.dataset.name = (r.n||'').toLowerCase();
    item.dataset.cat = r.c;
    item.innerHTML =
      '<div class="report-head"><span class="report-icon">📁</span>'+
      '<span class="report-name">'+esc(r.n)+'</span>'+
      '<span class="report-size">'+r.s+'</span>'+badge(r.c)+'</div>'+
      (r.d?'<div class="report-desc"><b>是什么：</b>'+esc(r.d)+'</div>':'')+
      (r.a?'<div class="report-advice"><b>清理建议：</b>'+esc(r.a)+'</div>':'')+
      '<div class="muted" style="font-size:12px;margin-top:2px">'+esc(r.p)+'</div>';
    item.dataset.path = r.p;
    (function(){ var h=item.querySelector('.report-head'); if(h){ var cp=document.createElement('button'); cp.className='copy-btn'; cp.textContent='📋 复制地址'; h.appendChild(cp); var ab2=document.createElement('button'); ab2.className='ai-analyze-btn'; ab2.textContent='🤖 AI分析'; ab2.dataset.path=r.p; ab2.dataset.name=r.n; ab2.dataset.size=r.s; h.appendChild(ab2); } })();
    list.appendChild(item);
  });
}
function renderBigUnknown(){
  const sec = document.getElementById('bigSec');
  const list = document.getElementById('bigList');
  const arr = DATA.big_unknown||[];
  if(!arr.length){ sec.style.display='none'; return; }
  list.innerHTML = '';
  arr.forEach(r=>{
    const item = document.createElement('div');
    item.className = 'report-item ai';
    item.dataset.name = (r.n||'').toLowerCase();
    item.dataset.ai = '1';
    const sw = (r.software?('<div class="ai-line"><b>📦 软件：</b>'+esc(r.software)+'</div>'):'');
    const pu = (r.purpose?('<div class="ai-line"><b>📝 用途：</b>'+esc(r.purpose)+'</div>'):'');
    const de = (r.deletable?('<div class="ai-line"><b>🗑 能否删除：</b>'+esc(r.deletable)+'</div>'):'');
    const su = (r.summary?('<div class="ai-summary"><b>📝 这是什么：</b>'+esc(r.summary)+'</div>'):'');
    item.innerHTML =
      '<div class="report-head"><span class="report-icon">📁</span>'+
      '<span class="report-name">'+esc(r.n)+'</span>'+
      '<span class="report-size">'+r.s+'</span>'+
      '<span class="badge cat-ai">🤖 AI 识别</span>'+lvBadge(r.level)+
      '<span class="muted">把握：'+(CONF_LABEL[r.confidence]||r.confidence)+'</span></div>'+
      (su || r.software||r.purpose||r.deletable ? '<div class="ai-block">'+su+sw+pu+de+'</div>' : '')+
      '<div class="muted" style="font-size:12px;margin-top:2px">'+esc(r.p)+'</div>';
    item.dataset.path = r.p;
    (function(){ var h=item.querySelector('.report-head'); if(h){ var cp=document.createElement('button'); cp.className='copy-btn'; cp.textContent='📋 复制地址'; h.appendChild(cp); var ab2=document.createElement('button'); ab2.className='ai-analyze-btn'; ab2.textContent='🤖 AI分析'; ab2.dataset.path=r.p; ab2.dataset.name=r.n; ab2.dataset.size=r.s; h.appendChild(ab2); } })();
    list.appendChild(item);
  });
}
function applyFilter(){
  const q = (document.getElementById('q').value||'').trim().toLowerCase();
  const f = document.getElementById('f').value;
  if(f==='ai'){
    document.querySelectorAll('#bigList .report-item').forEach(n=>{
      const ok = !q || (n.dataset.name||'').includes(q);
      n.style.display = ok ? 'block' : 'none';
    });
    document.querySelectorAll('#descList .report-item').forEach(n=> n.style.display='none');
    document.querySelectorAll('#topBody tr').forEach(tr=> tr.style.display='none');
    return;
  }
  document.querySelectorAll('#descList .report-item').forEach(n=>{
    const ok = (!q || (n.dataset.name||'').includes(q)) && (f==='all' || n.dataset.cat===f);
    n.style.display = ok ? 'block' : 'none';
  });
  document.querySelectorAll('#bigList .report-item').forEach(n=>{
    const ok = (!q || (n.dataset.name||'').includes(q));
    n.style.display = ok ? 'block' : 'none';
  });
  // 顶部最大表按名称过滤
  document.querySelectorAll('#topBody tr').forEach(tr=>{
    const txt = (tr.textContent||'').toLowerCase();
    tr.style.display = (!q || txt.includes(q)) ? '' : 'none';
  });
}
function copyPath(text, btn){
  var done = function(){ var t=btn.textContent; btn.textContent='✅ 已复制'; setTimeout(function(){btn.textContent=t;},1200); };
  var fb = function(){ var ta=document.createElement('textarea'); ta.value=text; ta.style.position='fixed'; ta.style.opacity='0'; document.body.appendChild(ta); ta.select(); try{document.execCommand('copy'); done();}catch(e){} document.body.removeChild(ta); };
  if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(text).then(done, fb); } else { fb(); }
}
document.addEventListener('click', function(e){
  if(!e.target || !e.target.closest) return;
  var t = e.target;
  var cp = t.closest('.copy-btn');
  if(cp){
    var ip = cp.getAttribute('data-path') || (cp.closest('.report-item') && cp.closest('.report-item').dataset.path) || (cp.closest('tr') && cp.closest('tr').dataset.path);
    if(ip) copyPath(ip, cp);
    return;
  }
  var ab = t.closest('.ai-analyze-btn');
  if(ab){
    var tr = ab.closest('tr');
    var item = ab.closest('.report-item') || (tr ? tr.cells[tr.cells.length-1] : null);
    if(item && !item.querySelector('.ai-result')){
      aiAnalyze(ab.getAttribute('data-path')||'', ab.getAttribute('data-name')||'', ab.getAttribute('data-size')||'', item);
    }
    return;
  }
});
function aiResultBlock(r){
  r = r||{};
  var lv = r.level||'caution';
  return '<div class="ai-block">'+
    '<span class="badge cat-ai">🤖 AI 分析</span>'+
    '<span class="badge lvl-'+lv+'">'+(LV_LABEL[lv]||'谨慎')+'</span>'+
    (r.confidence?'<span class="muted">把握：'+(CONF_LABEL[r.confidence]||r.confidence)+'</span>':'')+
    (r.summary?'<div class="ai-line"><b>📝 是什么：</b>'+esc(r.summary)+'</div>':'')+
    (r.deletable?'<div class="ai-line"><b>🗑 能否删除：</b>'+esc(r.deletable)+'</div>':'')+
    (r.impact?'<div class="ai-line"><b>⚠ 删除影响：</b>'+esc(r.impact)+'</div>':'')+
    '</div>';
}
// 浏览器端直接调用 DeepSeek（报告为自包含文件，无后端）。Key 仅存本机 localStorage。
function aiAnalyze(path, name, size, container){
  if(!container || container.querySelector('.ai-result')) return;
  var btn = container.querySelector('.ai-analyze-btn');
  if(btn){ btn.disabled = true; btn.textContent = '⏳ 分析中…'; }
  var keyEl = document.getElementById('dsKey');
  var key = (keyEl && keyEl.value.trim()) || (localStorage.getItem('ds_key')||'');
  if(!key){
    alert('请先在页面顶部输入 DeepSeek API Key（仅保存在你本机浏览器，用于调用 AI 分析）。');
    if(keyEl) keyEl.focus();
    if(btn){ btn.disabled=false; btn.textContent='🤖 AI分析'; }
    return;
  }
  var prompt = '下面文件地址中，这个文件夹是干什么的？' + path + ' （大小约 ' + (size||'未知') + '） 请判断：1) summary：一句话说明这个文件夹是做什么用的、里面一般存放什么内容；2) level：删除它的风险——safe=可放心删除（多为缓存/临时/可重建），caution=可删但要先备份或退出对应软件，never=不建议/禁止删除（删了会导致软件或系统异常）；3) deletable：一句话给「能不能删除」的具体结论；4) impact：如果删除，会影响什么（如：某软件无法启动、某游戏进度丢失、系统功能异常等），不确定写「影响未知，建议先备份」；5) confidence：你判断的把握 high / medium / low。 只输出严格 JSON：{"summary":"","level":"safe|caution|never","deletable":"","impact":"","confidence":"high|medium|low"}';
  fetch('https://api.deepseek.com/chat/completions', {
    method:'POST',
    headers:{'Content-Type':'application/json','Authorization':'Bearer '+key},
    body: JSON.stringify({model:'deepseek-chat', messages:[
      {role:'system', content:'你是 Windows 磁盘清理助手，只输出严格 JSON，不要多余文字。'},
      {role:'user', content: prompt}
    ], temperature:0.1})
  })
  .then(function(r){ return r.json().then(function(d){ return {ok:r.ok, d:d}; }); })
  .then(function(o){
    if(btn){ btn.disabled=false; btn.textContent='🤖 AI分析'; }
    if(!o.ok || o.d.error){ alert('分析失败：' + (o.d && o.d.error ? o.d.error.message : '未知错误')); return; }
    var text = (o.d.choices && o.d.choices[0]) ? (o.d.choices[0].message.content || '') : '';
    var m = text.indexOf('{'), e2 = text.lastIndexOf('}');
    var r = {};
    if(m>=0 && e2>m){ try{ r = JSON.parse(text.slice(m, e2+1)); }catch(_){} }
    if(!r || !r.summary){ alert('分析返回格式异常，请重试。'); return; }
    var box = document.createElement('div');
    box.className = 'ai-result';
    box.innerHTML = aiResultBlock(r);
    container.appendChild(box);
  })
  .catch(function(err){
    if(btn){ btn.disabled=false; btn.textContent='🤖 AI分析'; }
    alert('分析请求出错：' + err);
  });
}
window.addEventListener('DOMContentLoaded', function(){
  renderSummary(); renderTop(); renderDescribed(); renderBigUnknown();
  document.getElementById('q').addEventListener('input', applyFilter);
  document.getElementById('f').addEventListener('change', applyFilter);
  var ke = document.getElementById('dsKey');
  if(ke){ var sv = localStorage.getItem('ds_key')||''; ke.value = sv; ke.addEventListener('input', function(){ localStorage.setItem('ds_key', ke.value.trim()); }); }
});
"""


def export_focused_report_html(tree, out_path, top_n=500):
    """生成聚焦版报告：汇总 + 最大的 N 个 + 全部有说明的文件夹。文件小、可直开。"""
    payload = build_focused_payload(tree, top_n=top_n)
    data_json = html.escape(json.dumps(payload, ensure_ascii=False))
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>C 盘文件夹扫描报告（聚焦版）</title>
<style>{FOCUSED_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>C 盘文件夹扫描报告</h1>
  <div class="sub">工具只读扫描，不删除任何文件。聚焦「最大」与「已识别」的文件夹，便于清理决策。</div>
  <div class="controls">
    <input id="q" placeholder="搜索文件夹名 / 路径…">
    <select id="f">
      <option value="all">全部分类</option>
      <option value="ai">🤖 AI 识别（大文件夹）</option>
      <option value="safe">🟢 可直接删</option>
      <option value="software_clean">🔵 软件内清</option>
      <option value="confirm">🟡 需确认</option>
      <option value="never">🔴 禁止删</option>
    </select>
    <input id="dsKey" class="ds-key" placeholder="DeepSeek API Key（可选，用于逐文件夹 AI 分析）">
  </div>
  <div class="ds-hint">点每个文件夹的「🤖 AI分析」可调用 DeepSeek 分析其用途、能否删除及删除影响。Key 仅保存在你本机浏览器（localStorage），不会上传给他人。</div>
  <div class="report-summary"><div id="summary" class="summary-card"></div></div>
  <div class="section-title">📊 最大的 {top_n} 个文件夹</div>
  <div class="sec-top"><table>
    <thead><tr><th>#</th><th>大小</th><th>文件夹</th><th>分类</th><th>路径</th></tr></thead>
    <tbody id="topBody"></tbody>
  </table></div>
  <div class="section-title" id="bigSec">🤖 未收录大文件夹（&gt;2GB）AI 识别（{payload['big_unknown'] and len(payload['big_unknown']) or 0} 个）</div>
  <div id="bigList" class="report-list"></div>
  <div class="section-title">📁 全部「已识别 / 有说明」的文件夹（{payload['described'] and len(payload['described']) or 0} 个）</div>
  <div id="descList" class="report-list"></div>
</div>
<script>
const DATA = JSON.parse("{data_json}");
{FOCUSED_JS}
</script>
</body>
</html>
"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(page)
    return out_path

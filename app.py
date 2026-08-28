"""Flask 后端：后台扫描 + 轮询接口返回实时日志与目录树。

相比 SSE，轮询方案对浏览器更健壮（不怕超时/重连丢消息），且调试简单。
"""
import json
import logging
import os
import socket
import subprocess
import threading
import time
from flask import Flask, request, send_from_directory, jsonify, send_file

from scanner import scan_path, human_size, count_nodes, ScanAborted
from knowledge_base import KnowledgeBase
from ai_describer import AIDescriber
from analyzer import classify_tree, ai_describe, enrich
from report_exporter import export_focused_report_html

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder='static')

# ---- 扫描日志落盘：供"查查日志"用，捕获进度与异常（Werkzeug 默认只记请求行）----
scan_logger = logging.getLogger('scan')
scan_logger.setLevel(logging.INFO)
_scan_fh = logging.FileHandler(os.path.join(BASE, 'scan_debug.log'), encoding='utf-8')
_scan_fh.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
scan_logger.addHandler(_scan_fh)


def load_dotenv(path):
    """极简 .env 加载（避免额外依赖）。"""
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


def port_in_use(port, host='127.0.0.1'):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        s.close()


load_dotenv(os.path.join(BASE, '.env'))

KB = KnowledgeBase(os.path.join(BASE, 'rules.json'))
# AI 仅对「未收录且 > 1GB」的大文件夹做归属/用途/可删性识别，控制成本与耗时（第一层目录无视大小强制识别）。
AI = AIDescriber(
    api_key=os.getenv('DEEPSEEK_API_KEY'),
    base_url=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
    threshold=1 * 1024 * 1024 * 1024,
)


def key_is_usable():
    """判断服务端当前是否存在「看起来可用」的 DeepSeek Key。

    仅做格式/非空判断（不主动联网校验，避免每次启动都打 API）；
    真正的有效性由用户在前端「测试并进入」时联网验证。"""
    k = (os.getenv('DEEPSEEK_API_KEY') or '').strip()
    return bool(k) and k.lower() != 'your-key-here' and k.startswith('sk-')


def test_deepseek_key(api_key, base_url):
    """用一次轻量请求验证 Key 是否有效：调用 /v1/models（不消耗 token）。

    成功返回 (True, None)；失败返回 (False, '可读错误')。"""
    from openai import OpenAI
    # 优先尝试带代理（公司网络场景）；若环境没有 httpx 则走默认客户端。
    proxy = (os.getenv('DEEPSEEK_PROXY')
             or os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY'))
    client = None
    if proxy:
        try:
            import httpx
            client = OpenAI(api_key=api_key, base_url=base_url,
                            max_retries=2, http_client=httpx.Client(proxy=proxy))
        except Exception:
            client = None
    if client is None:
        client = OpenAI(api_key=api_key, base_url=base_url, max_retries=2)
    # /v1/models 不需消息、不打 token，仅验证鉴权与连通性
    client.models.list()
    return True, None


def rebuild_ai_with_key(api_key, base_url):
    """用新 Key 重建全局 AI 客户端（无需重启进程）。"""
    global AI
    AI = AIDescriber(
        api_key=api_key,
        base_url=base_url,
        threshold=1 * 1024 * 1024 * 1024,
    )
    return AI.enabled


def persist_deepseek_key(api_key):
    """把 Key 写回 .env（更新已有 DEEPSEEK_API_KEY 行，没有则追加），不入库、不打印。"""
    env_path = os.path.join(BASE, '.env')
    lines = []
    if os.path.exists(env_path):
        with open(env_path, encoding='utf-8') as f:
            lines = f.read().splitlines()
    new_lines = []
    replaced = False
    for ln in lines:
        if ln.strip().startswith('DEEPSEEK_API_KEY'):
            new_lines.append(f'DEEPSEEK_API_KEY={api_key}')
            replaced = True
        else:
            new_lines.append(ln)
    if not replaced:
        new_lines.append(f'DEEPSEEK_API_KEY={api_key}')
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines) + '\n')
    # 同步到当前进程环境变量，避免后续读取不一致
    os.environ['DEEPSEEK_API_KEY'] = api_key


# ---- 全局扫描状态（单进程内共享）----
logs = []                 # 扫描日志列表（字符串）
logs_base = 0             # 已被滚动丢弃的最早日志条数（用于绝对偏移）
logs_lock = threading.Lock()
scan_lock = threading.Lock()
scan_state = {
    'scanning': False,
    'done': False,
    'ai_done': False,       # AI 分析是否完成（success/fail 均为 True）
    'errored': False,
    'error': None,
    'progress': {'dirs': 0, 'files': 0},
    'started_at': 0,
    'last_progress_at': 0,
    'report_path': None,   # 扫描完成后自动生成的聚焦版 HTML 报告路径
    'report_ready': False,
}
# 扫描代次：每发起一次新扫描就 +1，旧 worker 通过 should_stop 感知到代次变化即安全退出。
scan_gen = 0
# 超过该时长（秒）无任何进度更新，视为扫描卡死，允许自动放行新扫描。
STALE_SCAN_SECONDS = 5 * 60
current_tree = None

# 日志保护：服务端最多保留最近 MAX_LOGS 条；每次状态查询最多回传 MAX_LOG_BATCH 条，
# 避免超大扫描时一次性把几十万条日志灌进浏览器导致卡死。
# MAX_LOG_BATCH 调小（1000 -> 60）：配合前端 rAF 涓流插入，每次 poll 只取少量，页面平滑更新不卡。
MAX_LOGS = 500000
MAX_LOG_BATCH = 60


def add_log(line):
    global logs_base
    with logs_lock:
        logs.append(line)
        if len(logs) > MAX_LOGS:
            drop = len(logs) - MAX_LOGS
            del logs[:drop]
            logs_base += drop
    try:
        scan_logger.info(line)   # 同时落盘，便于事后排查
    except Exception:
        pass


def _make_report(tree, path):
    """生成聚焦版 HTML 报告（小而可直开），返回路径；失败返回 None。"""
    try:
        slug = path.replace(':', '').replace('\\', '_').replace('/', '_').replace(' ', '_')[:60] or 'scan'
        out = os.path.join(BASE, 'reports', slug + '.html')
        export_focused_report_html(tree, out)
        return out
    except Exception as e:
        return f'ERR:{e}'


def scan_worker(path, my_gen):
    global current_tree, logs_base
    # 该 worker 专属的日志函数：若代次已被新扫描取代，则不再写日志/状态，避免污染新扫描。
    def log(line):
        if my_gen != scan_gen:
            return
        add_log(line)

    with logs_lock:
        logs.clear()
        logs_base = 0
    scan_state['progress'] = {'dirs': 0, 'files': 0}
    scan_state['scanning'] = True
    scan_state['done'] = False
    scan_state['ai_done'] = False
    scan_state['errored'] = False
    scan_state['error'] = None
    scan_state['started_at'] = time.time()
    scan_state['last_progress_at'] = time.time()

    # —— 进度日志节流 ——
    # 根因：每个目录都写一条日志，大目录（如 node_modules 上万个子目录）每秒产生几千条，
    # 后端 logs 无限增长、前端每批最多插 1000 条 DOM，主线程被占满 -> 鼠标挪不动 / 一次性蹦一大坨。
    # 修复：dirs 计数保持精确（供状态显示）；日志改为「每 ~0.35s 或每 150 个目录」才记一条摘要，
    # 大幅削减日志总量，前端呈现为平滑的涓流更新而非爆发。
    _prog_last_log = {'t': time.time(), 'n': 0, 'p': path, 'sz': 0, 'err': 0}

    def on_progress(p, size, error=None):
        scan_state['progress']['dirs'] += 1
        scan_state['last_progress_at'] = time.time()
        _prog_last_log['n'] += 1
        _prog_last_log['sz'] = size
        if error:
            _prog_last_log['err'] += 1
        now = time.time()
        if (now - _prog_last_log['t'] >= 0.35) or _prog_last_log['n'] >= 150:
            n = _prog_last_log['n']
            total = human_size(_prog_last_log['sz'])
            extra = f"  ⚠ {_prog_last_log['err']} 个访问失败" if _prog_last_log['err'] else ""
            line = f"[扫描] 已扫 {scan_state['progress']['dirs']} 个目录，最近：{p}  {total}{extra}"
            log(line)
            _prog_last_log['t'] = now
            _prog_last_log['n'] = 0
            _prog_last_log['err'] = 0

    try:
        if my_gen != scan_gen:
            return
        log(f"[开始] 扫描 {path}")
        tree = scan_path(path, on_progress=on_progress, should_stop=lambda: my_gen != scan_gen)
        if my_gen != scan_gen:
            log('⏹ 已取消（被新扫描取代）')
            return
        log(f"[扫描完成] 根目录大小 {tree['size_human']}，开始规则分类...")
        classify_tree(tree, KB)   # 规则分类必须成功，失败则整扫失败
        # —— 先交付目录树/报告：即使后续 AI 分析失败也不影响 ——
        current_tree = tree
        scan_state['done'] = True
        log(f"[分类完成] 共 {count_nodes(tree)} 个节点，目录树已可查看。开始可选的 AI 分析...")
        # AI 分析：尽力而为（DeepSeek 失败/超时不影响已生成的目录树与报告）
        # 第一层目录（扫描根的直接子目录）全部强制 AI 识别（无视大小阈值），扫描完成即给出
        # 「是什么 / 能不能删」结论；更深层仍渐进式（仅未识别且 >1GB 才自动分析），其余由用户
        # 点「🤖 AI分析」按需分析，避免巨树全量调 AI 长时间卡住。
        try:
            ai_describe(tree, KB, AI,
                        ai_progress=lambda n: log(f"[AI] 第一层目录全部（{n} 个）已交给 AI 识别；更深层仅未识别且 >1GB 的自动分析，其余可点「🤖 AI分析」按需分析..."),
                        should_stop=lambda: my_gen != scan_gen,
                        max_auto_depth=2)
            if my_gen != scan_gen:
                log('⏹ 已取消（被新扫描取代）')
                return
            log("[AI] 分析完成")
        except Exception as e:
            log(f"⚠ AI 分析失败（不影响目录树/报告，可稍后重扫补全）：{type(e).__name__}: {e}")
        finally:
            scan_state['ai_done'] = True
        # 自动生成聚焦版 HTML 报告（小巧可直开），供整盘等超大扫描使用
        log("📄 正在生成聚焦版 HTML 报告...")
        rp = _make_report(tree, path)
        if rp and not rp.startswith('ERR:'):
            scan_state['report_path'] = rp
            scan_state['report_ready'] = True
            log(f"📄 报告已生成：{rp}")
        elif rp and rp.startswith('ERR:'):
            log(f"⚠ 报告生成失败：{rp[4:]}")
        log(f"[全部完成] 根大小 {tree['size_human']}，可查看目录树/报告")
    except ScanAborted:
        log('⏹ 扫描已取消')
    except Exception as e:
        scan_state['errored'] = True
        scan_state['error'] = f"{type(e).__name__}: {e}"
        log(f"❌ 扫描异常：{type(e).__name__}: {e}")
    finally:
        scan_state['scanning'] = False


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/api/scan', methods=['POST'])
def api_scan():
    global scan_gen
    # 不依赖 Content-Type / 编码，直接从原始 body 解析，避免中文路径或 curl 编码导致 get_json 失败而回退默认值
    raw = request.get_data(as_text=True)
    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    path = (data.get('path') or 'C:\\Users\\12706').strip()
    if not os.path.isdir(path):
        return jsonify({'error': f'路径不存在或不是目录：{path}'}), 400
    with scan_lock:
        if scan_state['scanning']:
            force = bool(data.get('force'))
            last = scan_state.get('last_progress_at', 0) or 0
            # 卡死判定：长时间无进度更新（多半是扫描卡在某目录），自动放行新扫描。
            stale = (time.time() - last) > STALE_SCAN_SECONDS
            if not force and not stale:
                return jsonify({
                    'error': '已有扫描在进行中，请稍候',
                    'in_progress': True,
                }), 429
            # 让旧的扫描作废：提升代次，旧 worker 会在下一个检查点（目录/AI 批次）安全退出。
            scan_gen += 1
            for _ in range(100):  # 最多等待约 10s 让旧 worker 退出
                if not scan_state['scanning']:
                    break
                time.sleep(0.1)
        scan_gen += 1
        my_gen = scan_gen
        threading.Thread(target=scan_worker, args=(path, my_gen), daemon=True).start()
    return jsonify({'ok': True, 'path': path})


@app.route('/api/status')
def api_status():
    """增量返回日志。?after=N 表示只返回绝对索引 N 之后的新日志。

    为防卡死：单次最多回传 MAX_LOG_BATCH 条（取最新的），超出部分通过
    skipped 告知前端，由前端提示「已折叠更早的 N 条」。
    """
    try:
        after = int(request.args.get('after', 0))
    except ValueError:
        after = 0
    with logs_lock:
        local_after = max(0, after - logs_base)
        chunk = logs[local_after:]
        total = logs_base + len(logs)
    skipped = max(0, after - logs_base)
    if len(chunk) > MAX_LOG_BATCH:
        skipped += len(chunk) - MAX_LOG_BATCH
        chunk = chunk[-MAX_LOG_BATCH:]
    return jsonify({
        'scanning': scan_state['scanning'],
        'done': scan_state['done'],
        'ai_done': scan_state['ai_done'],
        'errored': scan_state['errored'],
        'error': scan_state['error'],
        'progress': scan_state['progress'],
        'report_ready': scan_state['report_ready'],
        'report_name': os.path.basename(scan_state['report_path']) if scan_state.get('report_path') else None,
        'log_offset': total,
        'logs': chunk,
        'skipped': skipped,
    })


# 目录树返回深度上限：超过该深度的子树在前端首次拉取时不下发完整节点，
# 而是折叠为占位节点（带后代文件夹数/大小），等用户在界面展开时再按需拉取。
# 目的：扫描 C:\Users\12706 这类巨盘会生成数十万~百万节点、序列化 300MB+ 的树，
# 前端一次性 JSON.parse 会撑爆主线程导致浏览器崩溃。分层按需下发彻底解决。
TREE_MAX_DEPTH = int(os.environ.get('TREE_MAX_DEPTH', '3'))


@app.route('/api/tree')
def api_tree():
    if current_tree is None:
        return jsonify({'ready': False})
    # 下发折叠后的树（仅前 TREE_MAX_DEPTH 层完整，深层为占位），体积从 300MB+ 降到几 MB
    return jsonify({'ready': True, 'tree': _fold_deep(current_tree, 0),
                    'max_depth': TREE_MAX_DEPTH})


def _fold_deep(node, depth):
    """递归：超过 TREE_MAX_DEPTH 的子孙折叠成占位节点（只保留聚合计数，不下发 children 全量）。"""
    if 'children' not in node:
        return node
    kids = node['children']
    if depth >= TREE_MAX_DEPTH:
        # 本层不再下发子节点细节，改为聚合占位
        ddirs = 0
        dbytes = 0
        for c in kids:
            if c.get('is_dir') and not c.get('is_link'):
                ddirs += 1 + c.get('descendant_dirs', 0)
                dbytes += c.get('size_bytes', 0) + c.get('descendant_bytes', 0)
        folded = dict(node)  # 浅拷贝，保留自身字段
        folded['children'] = []          # 不下发 grandchildren
        folded['truncated'] = True       # 前端据此显示「展开更多」按钮
        folded['descendant_dirs'] = ddirs
        folded['descendant_bytes'] = dbytes
        folded['descendant_size_human'] = human_size(dbytes)
        return folded
    out = dict(node)
    out['children'] = [_fold_deep(c, depth + 1) for c in kids]
    return out


def _find_node(node, path_norm):
    """在 current_tree 中按规范路径查找节点（用于按需展开）。"""
    cn = os.path.abspath(node['path']).rstrip('\\/').lower()
    if cn == path_norm:
        return node
    for c in node.get('children', []):
        r = _find_node(c, path_norm)
        if r:
            return r
    return None


@app.route('/api/tree_node')
def api_tree_node():
    """按需展开：返回某路径下一级子节点（同样做 TREE_MAX_DEPTH 相对折叠）。
    查询参数 ?path=绝对路径。用于前端点击「展开更多」时懒加载深层。"""
    if current_tree is None:
        return jsonify({'ready': False})
    raw = request.args.get('path', '').strip()
    if not raw:
        return jsonify({'error': '缺少 path 参数'}), 400
    target = _find_node(current_tree, os.path.abspath(raw).rstrip('\\/').lower())
    if not target:
        return jsonify({'error': '路径不在已扫描树中', 'not_found': True}), 404
    if not target.get('children'):
        return jsonify({'ready': True, 'children': [], 'truncated': False})
    # 目标层视为相对深度 0，再下发一层（depth+1），更深仍折叠
    children = [_fold_deep(c, 1) for c in target['children']]
    return jsonify({'ready': True, 'children': children, 'truncated': True,
                    'descendant_dirs': target.get('descendant_dirs', 0),
                    'descendant_bytes': target.get('descendant_bytes', 0)})


@app.route('/api/report')
def api_report():
    """返回最近一次扫描自动生成的聚焦版 HTML 报告（在浏览器新标签打开）。"""
    p = scan_state.get('report_path')
    if not p or not os.path.exists(p):
        return jsonify({'ready': False}), 404
    return send_file(p, mimetype='text/html')


@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    """对单个文件夹调用 DeepSeek 分析「是什么 / 能否删除 / 删除影响」。
    使用服务端 DeepSeek Key（不暴露给前端）；结果按 path 磁盘缓存，命中即返回。"""
    raw = request.get_data(as_text=True)
    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'error': '缺少 path 参数'}), 400
    if not AI.enabled:
        return jsonify({'error': 'AI 未启用（服务端缺少 DEEPSEEK_API_KEY）', 'ai_enabled': False}), 400
    name = data.get('name') or os.path.basename(path)
    size_human = data.get('size_human') or ''
    try:
        result = AI.analyze_one(path, name, size_human)
    except Exception as e:
        return jsonify({'error': f'分析失败：{type(e).__name__}: {e}'}), 500
    return jsonify({'ok': True, 'path': path, 'result': result})


@app.route('/api/health')
def api_health():
    return jsonify({'ai_enabled': AI.enabled, 'ai_threshold_mb': AI.threshold // (1024 * 1024)})


@app.route('/api/open', methods=['POST'])
def api_open():
    """在本地资源管理器中打开指定文件夹。

    安全护栏：目标必须位于最近一次扫描的根目录之内（与删除同源限制），
    不允许打开系统盘任意位置。命中保护名单时仍可打开（只读查看，不危险）。

    请求体：{ path: '...' }
    返回：{ ok: true } 或 { ok: false, error }
    """
    raw = request.get_data(as_text=True)
    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'ok': False, 'error': '缺少 path 参数'}), 400

    root = _scan_root_path()
    if not root:
        return jsonify({'ok': False, 'error': '尚未扫描任何目录，无法确认范围。请先扫描。'}), 400
    root_norm = os.path.abspath(root).rstrip('\\/').lower()
    target_norm = os.path.abspath(path).rstrip('\\/').lower()
    if not (target_norm == root_norm or target_norm.startswith(root_norm + '\\') or target_norm.startswith(root_norm + '/')):
        return jsonify({'ok': False, 'error': '目标不在扫描根目录之内，出于安全已拒绝打开。'}), 400
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': '路径不存在：' + path}), 404

    try:
        # 文件夹用资源管理器打开；文件则打开其所在目录并选中该文件
        if os.path.isdir(path):
            os.startfile(path)
        else:
            subprocess.run(['explorer', '/select,', path], check=False)
        return jsonify({'ok': True, 'path': path})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'打开失败：{type(e).__name__}: {e}'}), 500


@app.route('/api/key_status')
def api_key_status():
    """前端入口网关：返回服务端当前是否有「看起来可用」的 DeepSeek Key。

    has_key=True 时前端直接放行进入功能界面；
    has_key=False 时前端弹出 Key 输入/测试弹窗，测试通过才放行。
    """
    return jsonify({'has_key': key_is_usable(), 'ai_enabled': AI.enabled})


@app.route('/api/set_key', methods=['POST'])
def api_set_key():
    """接收前端提交的 DeepSeek Key，联网测试有效性；通过则写回 .env 并重建 AI 客户端。

    请求体：{ key: 'sk-...' }，可选 base_url（默认 https://api.deepseek.com）
    返回：{ ok: true } 或 { ok: false, error: '可读原因' }
    """
    raw = request.get_data(as_text=True)
    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    key = (data.get('key') or '').strip()
    base_url = (data.get('base_url') or os.getenv('DEEPSEEK_BASE_URL') or 'https://api.deepseek.com').strip()
    if not key:
        return jsonify({'ok': False, 'error': '请先填入 DeepSeek API Key'}), 400
    # 基础格式校验
    if not key.startswith('sk-'):
        return jsonify({'ok': False, 'error': 'Key 格式看起来不对（DeepSeek Key 一般以 sk- 开头）'}), 400
    try:
        ok, err = test_deepseek_key(key, base_url)
    except Exception as e:
        name = type(e).__name__
        msg = str(e)
        if 'Authentication' in msg or '401' in msg:
            return jsonify({'ok': False, 'error': 'Key 无效或已过期（DeepSeek 返回鉴权失败）'})
        if 'Connection' in name or 'Timeout' in name or 'Connect' in name:
            return jsonify({'ok': False, 'error': '连接 DeepSeek 失败（网络/代理问题）。若公司网需代理，请在服务端 .env 加 DEEPSEEK_PROXY 后重试；也可能是 DeepSeek 临时不可用。'})
        return jsonify({'ok': False, 'error': f'测试失败：{name} {msg[:160]}'})
    if not ok:
        return jsonify({'ok': False, 'error': err or '测试失败'})
    # 测试通过：写回 .env + 重建客户端
    try:
        persist_deepseek_key(key)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Key 有效，但写入 .env 失败：{e}'}), 500
    rebuild_ai_with_key(key, base_url)
    return jsonify({'ok': True})


@app.after_request
def _no_cache(resp):
    # 禁止浏览器缓存，避免改了 JS 后用户还跑旧逻辑
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    return resp


# ---- 删除功能：仅允许删除「已扫描根目录之内」的路径，且拒绝保护名单 ----

def _scan_root_path():
    """返回最近一次扫描的根路径（用于限制删除范围，避免误删系统目录）。"""
    return current_tree['path'] if current_tree else None


def _is_protected(path):
    """判断路径是否命中保护名单（系统关键目录 / rules.json 的 protected 列表）。"""
    norm = path.replace('/', '\\').lower().rstrip('\\')
    # 系统级绝对保护（无论扫描哪个根都不可删）
    sys_protect = ['windows', 'program files', 'programdata', 'appdata',
                   'ntuser', '.ssh', '.gitconfig', '.docker', '.ollama']
    base = os.path.basename(norm)
    for p in sys_protect:
        if norm.endswith('\\' + p) or base == p:
            return True
    # rules.json 的 protected 列表
    for p in getattr(KB, 'protected', []) or []:
        pl = p.replace('/', '\\').lower()
        if norm.endswith('\\' + pl) or base == pl:
            return True
    return False


@app.route('/api/delete', methods=['POST'])
def api_delete():
    """删除一个文件夹或文件（默认进回收站，失败回退永久删除）。

    安全护栏：
    1. 目标路径必须在「最近一次扫描的根目录」之内（current_tree.path），
       不允许删除根目录之外的任意路径（防误删系统盘）。
    2. 命中保护名单（系统关键目录 / rules.json protected）直接拒绝。
    3. 删除前服务端再次确认路径存在且为目录/文件。

    请求体：{ path: '...' }
    返回：{ ok: true, path, parent, method } 或 { ok: false, error }
    """
    raw = request.get_data(as_text=True)
    data = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'ok': False, 'error': '缺少 path 参数'}), 400

    root = _scan_root_path()
    if not root:
        return jsonify({'ok': False, 'error': '尚未扫描任何目录，无法确认删除范围。请先扫描。'}), 400
    # 规范化比较：目标必须是 root 的子路径（或就是 root 本身禁止删）
    root_norm = os.path.abspath(root).rstrip('\\/').lower()
    path_norm = os.path.abspath(path).rstrip('\\/').lower()
    if path_norm == root_norm:
        return jsonify({'ok': False, 'error': '不能删除正在扫描的根目录本身。'}), 400
    if not (path_norm.startswith(root_norm + '\\') or path_norm.startswith(root_norm + '/')):
        return jsonify({'ok': False, 'error': '目标不在已扫描目录范围内，出于安全拒绝删除。'}), 400
    if _is_protected(path):
        return jsonify({'ok': False, 'error': '该路径在保护名单中（系统/关键目录），禁止删除。'}), 400

    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': '路径不存在：' + path}), 404

    parent = os.path.dirname(path)
    try:
        method = 'recycle'
        try:
            import send2trash
            send2trash.send2trash(path)
        except Exception:
            # 回收站不可用（无 send2trash / 权限不足 / 路径过长等）：回退永久删除，
            # 已在前端二次确认。目录用 rmtree，文件用 remove。
            import shutil
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            method = 'permanent'
        # 同时从服务端缓存的目录树中移除该节点，供前端刷新
        _remove_from_tree(current_tree, path_norm)
        return jsonify({'ok': True, 'path': path, 'parent': parent, 'method': method})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'删除失败：{type(e).__name__}: {e}'}), 500


def _remove_from_tree(node, path_norm):
    """从 current_tree 中递归移除指定路径的节点（用于删除后刷新视图）。"""
    if not node or 'children' not in node:
        return False
    for i, c in enumerate(node['children']):
        cn = os.path.abspath(c['path']).rstrip('\\/').lower()
        if cn == path_norm:
            node['children'].pop(i)
            # 重新累加父节点大小
            try:
                node['size_bytes'] -= c.get('size_bytes', 0)
                node['size_human'] = human_size(node['size_bytes'])
            except Exception:
                pass
            return True
        if _remove_from_tree(c, path_norm):
            return True
    return False


if __name__ == '__main__':
    # 端口默认钉在 5001：5000 常被本机其它项目（如 knowledge-tree-app）占用，
    # 之前自动顺延到 5001 导致用户习惯的 5000 地址变成别的应用、看不到「扫描」按钮。
    # 现固定 5001，可用 .env 的 SCANNER_PORT 覆盖。
    PORT = int(os.getenv('SCANNER_PORT', os.getenv('PORT', 5001)))
    # 端口被占用则自动顺延，避免绑定失败（也能绕开残留僵尸端口）
    tried = PORT
    while port_in_use(PORT):
        print(f"⚠ 端口 {PORT} 已被占用，自动尝试下一个端口…")
        PORT += 1
        if PORT - tried > 100:
            print("无法找到可用端口，退出。")
            raise SystemExit(1)
    print(f"访问 http://127.0.0.1:{PORT}")
    app.run(host='127.0.0.1', port=PORT, threaded=True)

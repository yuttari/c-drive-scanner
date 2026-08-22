"""分析编排：先用规则库分类所有节点，再对规则未命中且 >= 阈值的文件夹批量调 AI。"""


def classify_tree(tree, kb):
    """仅规则库分类（必须成功，失败则整扫失败）。不会抛 IO/网络异常。"""
    def collect(node):
        res = kb.classify(node)
        if res:
            node.update(res)
        else:
            # 规则库未命中 -> 标记为「未识别」(category=unknown)。保留节点上已有的 description/advice
            # （多来自旧缓存，避免低阈值(<2GB)已说明的文件夹在阈值提升后被清空）。
            node['category'] = 'unknown'
        if node['is_dir'] and not node['is_link'] and node['accessible']:
            for c in node['children']:
                collect(c)
    collect(tree)
    return tree


def ai_describe(tree, kb, ai, ai_progress=None, should_stop=None, max_auto_depth=2):
    """对规则未命中且 >= 阈值的文件夹批量调 AI。本函数不保证成功——调用方应自行 try/except，
    失败也不影响已生成的目录树/报告。

    渐进式分析：只自动批量分析「前 max_auto_depth 层」(默认根下第一、二级) 的未识别大文件夹，
    避免一次扫描对深层几十上百个 >2GB 文件夹全量调 AI 导致扫描完成后长时间卡住（scanning 一直
    True、前端转圈）。更深的文件夹不在自动批量里——用户可在界面点「🤖 AI分析」按钮按需分析
    （/api/analyze 单文件夹分析，带磁盘缓存，不浪费额度）。
    """
    unknown_big = []

    def collect(node, depth):
        if node['is_dir'] and not node['is_link'] and node['accessible']:
            # 仅前 max_auto_depth 层纳入自动批量；深层留待用户点击分析
            if depth <= max_auto_depth \
                    and node.get('category') == 'unknown' \
                    and node['size_bytes'] >= ai.threshold:
                unknown_big.append(node)
            for c in node['children']:
                collect(c, depth + 1)

    collect(tree, 0)

    if ai.enabled and unknown_big:
        if should_stop and should_stop():
            return tree
        if ai_progress:
            ai_progress(len(unknown_big))
        ai.describe_batch([
            {'path': n['path'], 'name': n['name'], 'size_human': n['size_human']}
            for n in unknown_big
        ])
        for n in unknown_big:
            if should_stop and should_stop():
                return tree
            if n['path'] in ai.cache:
                n.update(ai.cache[n['path']])
                # 凡经大模型分析的文件夹，强制标记为「🤖 AI 识别」，不再显示「未收录」。
                if n.get('ai_analyzed'):
                    n['category'] = 'ai'
    return tree


def enrich(tree, kb, ai, ai_progress=None, should_stop=None, max_auto_depth=2):
    """兼容旧调用方（run_and_export / rebuild）：先分类，再做 AI。"""
    classify_tree(tree, kb)
    ai_describe(tree, kb, ai, ai_progress=ai_progress, should_stop=should_stop,
                max_auto_depth=max_auto_depth)
    return tree

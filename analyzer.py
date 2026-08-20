"""分析编排：先用规则库分类所有节点，再对规则未命中且 >= 阈值的文件夹批量调 AI。"""


def classify_tree(tree, kb):
    """仅规则库分类（必须成功，失败则整扫失败）。不会抛 IO/网络异常。"""
    def collect(node):
        res = kb.classify(node)
        if res:
            node.update(res)
        else:
            # 规则库未命中 -> 标记为「未收录」。保留节点上已有的 description/advice
            # （多来自旧缓存，避免低阈值(<2GB)已说明的文件夹在阈值提升后被清空）。
            node['category'] = 'unknown'
        if node['is_dir'] and not node['is_link'] and node['accessible']:
            for c in node['children']:
                collect(c)
    collect(tree)
    return tree


def ai_describe(tree, kb, ai, ai_progress=None, should_stop=None):
    """对规则未命中且 >= 阈值的文件夹批量调 AI。本函数不保证成功——调用方应自行 try/except，
    失败也不影响已生成的目录树/报告。"""
    unknown_big = []

    def collect(node):
        if node['is_dir'] and not node['is_link'] and node['accessible']:
            if node.get('category') == 'unknown' and node['size_bytes'] >= ai.threshold:
                unknown_big.append(node)
            for c in node['children']:
                collect(c)

    collect(tree)

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


def enrich(tree, kb, ai, ai_progress=None, should_stop=None):
    """兼容旧调用方（run_and_export / rebuild）：先分类，再做 AI。"""
    classify_tree(tree, kb)
    ai_describe(tree, kb, ai, ai_progress=ai_progress, should_stop=should_stop)
    return tree

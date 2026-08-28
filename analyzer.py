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
    """自动 AI 识别编排。

    规则：
    - 第一层目录（depth==1，即被扫描根的直接子目录）：无论大小、无论是否已被规则库识别，
      都强制交给 AI 识别，扫描完成后即给出「这个文件夹是干什么的 / 能不能删」的结论。
      （系统级「禁止删」保护项 category=='never' 除外，避免 AI 误判引发误删。）
    - 更深层（depth 2..max_auto_depth）：仍渐进式，仅对「规则未命中且 >= 阈值(2GB)」的大文件夹
      自动分析，避免整棵巨树一次性全量调 AI 导致扫描完成后长时间卡住；更深的可点
      「🤖 AI分析」按需分析。
    """
    auto_list = []  # (node, orig_category)

    # 根节点（depth=0）：若未被规则库识别且可访问，也交给 AI（与 depth==1 同等对待）。
    # 原逻辑从 depth=0 递归但 depth==0 不命中任何分支，导致扫描根自身永远「未识别」。
    if (tree.get('is_dir') and not tree.get('is_link') and tree.get('accessible')
            and tree.get('category') == 'unknown'):
        auto_list.append((tree, 'unknown'))

    def collect(node, depth):
        if node['is_dir'] and not node['is_link'] and node['accessible']:
            if depth <= max_auto_depth:
                cat = node.get('category')
                if cat == 'never':
                    pass  # 系统级禁止删：保留原分类，不交 AI
                elif depth == 1:
                    auto_list.append((node, cat))              # 第一层：全部纳入 AI 识别
                elif cat == 'unknown' and node['size_bytes'] >= ai.threshold:
                    auto_list.append((node, cat))              # 深层：渐进式，仅未识别大文件夹
            for c in node['children']:
                collect(c, depth + 1)

    collect(tree, 0)

    if ai.enabled and auto_list:
        if should_stop and should_stop():
            return tree
        if ai_progress:
            ai_progress(len(auto_list))
        ai.describe_batch([
            {'path': n['path'], 'name': n['name'], 'size_human': n['size_human']}
            for n, _ in auto_list
        ])
        for n, orig_cat in auto_list:
            if should_stop and should_stop():
                return tree
            if n['path'] in ai.cache:
                cached = ai.cache[n['path']]
                n.update(cached)   # cached 含 category='ai'、summary、deletable 等
                if n.get('ai_analyzed'):
                    # 原本未识别 -> 标记为「🤖 AI 识别」；规则已识别 -> 保留原 badge，仅附加 AI 说明
                    n['category'] = 'ai' if orig_cat == 'unknown' else orig_cat
    return tree


def enrich(tree, kb, ai, ai_progress=None, should_stop=None, max_auto_depth=2):
    """兼容旧调用方（run_and_export / rebuild）：先分类，再做 AI。"""
    classify_tree(tree, kb)
    ai_describe(tree, kb, ai, ai_progress=ai_progress, should_stop=should_stop,
                max_auto_depth=max_auto_depth)
    return tree

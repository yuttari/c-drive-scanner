"""全量递归扫描：计算每个文件夹（含子树）总大小，处理权限错误与 junction/软链。"""
import os


class ScanAborted(Exception):
    """扫描被取消（由 should_stop 触发），用于干净地终止递归。"""


def human_size(n):
    if n < 1024:
        return f"{n} B"
    units = ['KB', 'MB', 'GB', 'TB', 'PB']
    i = -1
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.2f} {units[i]}"


def _new_node(path, is_dir=True, is_link=False, size=0):
    return {
        'name': os.path.basename(path.rstrip(os.sep)) or path,
        'path': path,
        'is_dir': is_dir,
        'accessible': True,
        'is_link': is_link,
        'size_bytes': size,
        'size_human': human_size(size),
        'category': 'unknown',
        'description': '',
        'advice': '',
        'children': [],
        'error': None,
    }


def _scan(path, on_progress, depth, max_depth, should_stop=None):
    if should_stop and should_stop():
        raise ScanAborted()
    node = _new_node(path)
    try:
        entries = list(os.scandir(path))
    except (PermissionError, OSError) as e:
        node['accessible'] = False
        node['error'] = str(e)
        if on_progress:
            on_progress(path, 0, error=str(e))
        return node

    total = 0
    children = []
    for entry in entries:
        if should_stop and should_stop():
            raise ScanAborted()
        try:
            is_link = entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction())
            st = entry.stat(follow_symlinks=False)
            if is_link:
                c = _new_node(entry.path, is_dir=entry.is_dir(follow_symlinks=False), is_link=True, size=st.st_size)
                c['description'] = '符号链接 / junction（不递归，避免重复计算）'
                children.append(c)
                total += st.st_size
                continue
            if entry.is_dir(follow_symlinks=False):
                if depth >= max_depth:
                    c = _new_node(entry.path)
                    c['description'] = '已达最大扫描深度'
                    children.append(c)
                    continue
                sub = _scan(entry.path, on_progress, depth + 1, max_depth, should_stop)
                children.append(sub)
                total += sub['size_bytes']
            else:
                sz = st.st_size
                c = _new_node(entry.path, is_dir=False, size=sz)
                children.append(c)
                total += sz
        except (PermissionError, OSError) as e:
            c = _new_node(entry.path, is_dir=entry.is_dir(follow_symlinks=False))
            c['accessible'] = False
            c['error'] = str(e)
            children.append(c)

    children.sort(key=lambda c: c.get('size_bytes', 0), reverse=True)
    node['children'] = children
    node['size_bytes'] = total
    node['size_human'] = human_size(total)
    if on_progress:
        on_progress(path, total)
    return node


def scan_path(path, on_progress=None, max_depth=50, should_stop=None):
    """扫描 path 下的完整目录树，返回根节点字典。

    should_stop: 无参 callable，返回 True 时立即中止扫描（抛 ScanAborted）。
    """
    return _scan(path, on_progress, 0, max_depth, should_stop)


def count_nodes(node):
    n = 1
    for c in node.get('children', []):
        n += count_nodes(c)
    return n

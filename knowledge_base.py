"""规则库：已知路径 -> 说明 / 分类。同时提供受保护硬名单（优先级高于 AI）。"""
import json
import os


class KnowledgeBase:
    def __init__(self, rules_path):
        with open(rules_path, encoding='utf-8') as f:
            data = json.load(f)
        self.rules = data.get('rules', [])
        self.protected = data.get('protected', [])

    def classify(self, node):
        """返回 dict 或 None。受保护项永远 never。
        匹配语义：path=路径尾部匹配；name=目录名相等；endswith=文件名后缀；
        name_under_parent=父目录下某名。均只匹配节点自身，不被祖先路径误伤。"""
        path = node['path'].replace('/', '\\')
        low = path.lower()
        for p in self.protected:
            pl = p.lower().replace('/', '\\')
            # 只匹配节点自身（精确或路径尾部），不株连其下所有子孙目录
            if low == pl or low.endswith('\\' + pl):
                return {
                    'category': 'never',
                    'description': '系统 / 配置关键项（受保护），严禁删除',
                    'advice': '千万别动，删除会导致软件或系统损坏',
                    'cleanable': False,
                }
        norm = path
        base = os.path.basename(norm).lower()
        for r in self.rules:
            m = r['match'].replace('/', '\\')
            mt = r.get('match_type', 'path')
            if mt == 'path' and (norm.lower() == m.lower() or norm.lower().endswith('\\' + m.lower())):
                return self._apply(r)
            if mt == 'name' and base == m.lower():
                return self._apply(r)
            if mt == 'endswith' and base.endswith(m.lower()):
                return self._apply(r)
            if mt == 'name_under_parent' and norm.lower().endswith('\\' + m.lower()):
                return self._apply(r)
        return None

    @staticmethod
    def _apply(r):
        return {
            'category': r['category'],
            'description': r.get('description', ''),
            'advice': r.get('advice', ''),
            'cleanable': r.get('category') == 'safe',
        }

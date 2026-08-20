"""一键扫描指定目录并导出自包含 HTML 报告。

用法：
    python run_and_export.py "C:\\Users\\12706\\.cache"
    python run_and_export.py "C:\\Users\\12706"        # 全量

输出：reports/<slug>.html
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from scanner import scan_path, count_nodes
from knowledge_base import KnowledgeBase
from ai_describer import AIDescriber
from analyzer import enrich
from report_exporter import export_report_html


def load_dotenv(path):
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    if len(sys.argv) < 2:
        print("用法: python run_and_export.py <目录路径>")
        sys.exit(1)
    path = sys.argv[1].strip()
    if not os.path.isdir(path):
        print("路径不存在或不是目录:", path)
        sys.exit(1)

    load_dotenv(os.path.join(BASE, '.env'))
    KB = KnowledgeBase(os.path.join(BASE, 'rules.json'))
    AI = AIDescriber(
        api_key=os.getenv('DEEPSEEK_API_KEY'),
        base_url=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
    )

    print(f"[1/3] 扫描 {path} ...")
    tree = scan_path(path)
    print(f"      根大小 {tree['size_human']}，节点数 {count_nodes(tree)}")

    print("[2/3] AI 分析（规则库命中项跳过，未命中且 >=50MB 才调 AI）...")
    enrich(tree, KB, AI, ai_progress=lambda n: print(f"      [AI] 分析 {n} 个文件夹..."))

    slug = path.replace(':', '').replace('\\\\', '_').replace('/', '_')
    slug = slug.replace(' ', '_')[:60] or 'scan'
    out = os.path.join(BASE, 'reports', slug + '.html')
    export_report_html(tree, out)
    # 另存原始树，便于以后直接重导出（改样式/剪枝）而无需重新扫描 300GB
    tree_json = os.path.join(BASE, 'reports', slug + '.tree.json')
    import json as _json
    with open(tree_json, 'w', encoding='utf-8') as tf:
        _json.dump(tree, tf, ensure_ascii=False)
    print(f"[3/3] 报告已导出: {out}")
    print(f"      原始树已存: {tree_json}")
    print("DONE:" + os.path.abspath(out))


if __name__ == '__main__':
    main()

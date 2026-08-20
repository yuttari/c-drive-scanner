"""从已生成的大报告抽出目录树，用修复后的规则库 + AI 缓存重新分类，
并导出「聚焦版」HTML 报告。无需重新扫描 300GB，AI 走缓存不烧接口。"""
import json
import html
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from knowledge_base import KnowledgeBase
from ai_describer import AIDescriber
from analyzer import enrich
from report_exporter import export_focused_report_html, prune_files

BIG = os.path.join(BASE, "reports", "C", "Users", "12706.html")
TREE_JSON = os.path.join(BASE, "reports", "C", "Users", "12706.tree.json")
OUT = os.path.join(BASE, "reports", "C", "Users", "12706.html")


def load_pruned_tree():
    if os.path.exists(TREE_JSON):
        print("从 tree.json 加载目录树...")
        with open(TREE_JSON, encoding="utf-8") as f:
            return json.load(f)
    print("从大报告 HTML 抽取目录树...")
    with open(BIG, encoding="utf-8") as f:
        txt = f.read()
    i = txt.find('JSON.parse("') + len('JSON.parse("')
    j = txt.find('");', i)
    raw = txt[i:j].replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    tree = json.loads(raw)
    tree = prune_files(tree)
    return tree


def load_dotenv(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    tree = load_pruned_tree()
    # 保存 tree.json 供以后快速重导出
    with open(TREE_JSON, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False)
    print("已保存 tree.json")

    load_dotenv(os.path.join(BASE, ".env"))
    KB = KnowledgeBase(os.path.join(BASE, "rules.json"))
    AI = AIDescriber(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    print("重新分类（修复后的规则库 + AI 缓存）...")
    enrich(tree, KB, AI)
    # 重分类后再存一次 tree.json（含正确的分类/说明），以后重导出无需重扫
    with open(TREE_JSON, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False)
    print("已更新 tree.json")
    print("导出聚焦版报告...")
    out = export_focused_report_html(tree, OUT, top_n=500)
    sz = os.path.getsize(out)
    print("完成: %s (%.2f MB)" % (out, sz / 1024 / 1024))
    print("DONE:" + os.path.abspath(out))


if __name__ == "__main__":
    main()

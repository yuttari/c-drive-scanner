# C 盘文件夹扫描工具

给定文件夹路径，**全量递归扫描**，统计每个文件夹总大小，并用 **DeepSeek** 解释每个文件夹是干什么的、能不能清理。扫描过程实时展示日志，结果以可折叠树 + 彩色徽章呈现。

> ⚠️ 本工具**只读**，不删除任何文件。删除请自行谨慎。

## 功能

- 全量递归扫描，计算每个文件夹（含子树）总大小
- 扫描中通过 SSE 实时推送日志，不再干等
- 规则库（`rules.json`）+ DeepSeek 兜底：已知目录秒回，未知目录（≥50MB）批量调 AI
- 四级分类徽章：🟢 可直接删 / 🔵 软件内清 / 🟡 需确认 / 🔴 禁止删
- 可折叠目录树 + 名称搜索 + 按分类筛选
- 受保护硬名单：注册表、`.ssh`、系统目录等永远判"禁止删"，AI 不覆盖

## 运行

```bash
pip install -r requirements.txt
# 配置 DeepSeek key（也可直接填 .env）
cp .env.example .env   # 或手动创建 .env，写入：
#   DEEPSEEK_API_KEY=你的key
#   DEEPSEEK_BASE_URL=https://api.deepseek.com
python app.py
```

浏览器打开 http://127.0.0.1:5000 ，路径填 `C:\Users\12706` ，点「扫描」。

> AI 结果按路径缓存到 `cache.json`，重复扫描同目录秒回、零调用。

## 目录结构

```
app.py           Flask 后端 + SSE 实时日志
scanner.py       全量递归扫描 + 大小计算 + 权限/junction 处理
knowledge_base.py 规则库引擎（安全兜底）
ai_describer.py  DeepSeek 批量分析 + 磁盘缓存
analyzer.py      规则分类 + 批量 AI 编排
rules.json       已知路径 → 说明/分类（可手动增删）
static/          前端（index.html / app.js / style.css）
```

## 调参

- AI 大小阈值：改 `app.py` 中 `AIDescriber(..., threshold=...)`（默认 50MB）
- 模型：默认 `deepseek-chat`
- 规则库：直接编辑 `rules.json`，无需改代码

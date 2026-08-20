"""DeepSeek AI 兜底：对规则库未命中（未收录）的大文件夹，识别其归属软件、用途、可删性。
带磁盘缓存；缓存结构变更时通过 CACHE_VERSION 自动失效旧缓存。
"""
import json
import os
import time

CACHE_FILE = os.path.join(os.path.dirname(__file__), 'cache.json')


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            return json.load(open(CACHE_FILE, encoding='utf-8'))
        except Exception:
            return {}
    return {}


def save_cache(cache):
    try:
        json.dump(cache, open(CACHE_FILE, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
    except Exception:
        pass


class AIDescriber:
    def __init__(self, api_key, base_url, model='deepseek-chat',
                 threshold=2 * 1024 * 1024 * 1024, enabled=True,
                 proxy=None, max_retries=4):
        self.threshold = threshold
        self.enabled = bool(api_key) and enabled
        self.cache = load_cache()
        self.client = None
        if self.enabled:
            try:
                from openai import OpenAI
                import httpx
                # 支持代理：公司网络/防火墙环境下 Python 可能无法直连 api.deepseek.com，
                # 可通过环境变量 DEEPSEEK_PROXY / HTTPS_PROXY / HTTP_PROXY 指定代理（http/https 均可）。
                proxy = (proxy or os.getenv('DEEPSEEK_PROXY')
                         or os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY'))
                http_client = httpx.Client(proxy=proxy) if proxy else None
                self.client = OpenAI(api_key=api_key, base_url=base_url,
                                     max_retries=max_retries, http_client=http_client)
                self.model = model
            except Exception:
                self.enabled = False

    def _chat_completion(self, messages, max_attempts=3, timeout=120):
        """带重试地调用 chat.completions.create。

        DeepSeek API 偶发网络抖动会抛 APIConnectionError（连接错误），
        这类瞬时失败重试通常即可恢复；其余异常直接上抛由调用方处理。
        """
        from openai import APIConnectionError
        last_err = None
        for attempt in range(max_attempts):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    timeout=timeout,
                )
            except APIConnectionError as e:
                last_err = e
                if attempt < max_attempts - 1:
                    time.sleep(1 + attempt)   # 简单退避后重试
                    continue
                raise
        if last_err:
            raise last_err

    def describe_batch(self, items, batch_size=30):
        """items: list of {path, name, size_human}（均为「未收录且 > 阈值」的文件夹）。
        结果按 path 写入缓存。分批调用（避免单次 prompt 过大导致截断/超限），编号作 JSON key 避免同名冲突。

        每个文件夹返回结构化字段：
          summary     一句话总结——这个文件夹是干什么的、里面一般是什么（★主输出，展示在文件夹下方）
          software    归属软件/程序（不确定写「未知软件」）
          level       删除风险 safe / caution / never
          deletable   「能不能删除」的具体建议（一句话）
          confidence  判断把握 high / medium / low
        """
        # 仅跳过「已有新版结构化结果(含 ai_analyzed)」的条目；旧版缓存(只有 description 等)
        # 仍然保留给 <2GB 的小文件夹使用，不浪费额度重算，避免历史说明丢失。
        to_ask = [it for it in items
                  if not (it['path'] in self.cache and self.cache[it['path']].get('ai_analyzed'))]
        if not to_ask:
            return
        total = len(to_ask)
        done = 0
        for i in range(0, total, batch_size):
            chunk = to_ask[i:i + batch_size]
            # 用户风格的提示词：把路径直接喂给模型「这个文件夹是干什么的？{path}」
            listing = "\n".join(
                f"{idx + 1}. 下面文件地址中，这个文件夹是干什么的？{it['path']} （大小约 {it['size_human']}）"
                for idx, it in enumerate(chunk)
            )
            prompt = (
                "下面给出 Windows 用户目录下若干【规则库未收录】的大文件夹地址及大小。\n"
                "请针对每个地址回答「这个文件夹是干什么的」，并只输出严格 JSON：\n"
                "1) summary：用一句话总结这个文件夹是干什么的、里面一般存放什么内容（这是最重要的输出）；\n"
                "2) software：它属于哪个软件/程序（如不确定写“未知软件”）；\n"
                "3) level：删除它的风险——safe=可放心删除（多为缓存/临时/可重建），"
                "caution=可删但要先备份或退出对应软件，never=不建议/禁止删除（删了会导致软件或系统异常）；\n"
                "4) deletable：一句话给「能不能删除」的具体建议；\n"
                "5) confidence：你判断的把握 high / medium / low。\n"
                "只输出严格 JSON，key 用编号（如 \"1\"），值为对象："
                '{"summary":"","software":"","level":"safe|caution|never","deletable":"","confidence":"high|medium|low"}。\n'
                "文件夹：\n" + listing
            )
            try:
                resp = self._chat_completion([
                    {"role": "system", "content": "你是 Windows 磁盘清理助手，只输出严格 JSON，不要多余文字。"},
                    {"role": "user", "content": prompt},
                ])
                text = resp.choices[0].message.content or ""
                data = self._parse_json(text)
                for idx, it in enumerate(chunk):
                    key = str(idx + 1)
                    if key in data and isinstance(data[key], dict):
                        o = data[key]
                        level = o.get('level', 'caution')
                        if level not in ('safe', 'caution', 'never'):
                            level = 'caution'
                        conf = o.get('confidence', 'low')
                        if conf not in ('high', 'medium', 'low'):
                            conf = 'low'
                        sw = (o.get('software') or '').strip()
                        su = (o.get('summary') or '').strip()
                        de = (o.get('deletable') or '').strip()
                        self.cache[it['path']] = {
                            'category': 'ai',        # 已用大模型分析，标记为「🤖 AI 识别」
                            'summary': su,
                            'software': sw,
                            'purpose': su,           # purpose 沿用 summary，便于前端统一取数
                            'deletable': de,
                            'level': level,
                            'confidence': conf,
                            'ai_analyzed': True,
                            'description': su or (f"属于【{sw}】".strip() if sw else ''),
                            'advice': de,
                        }
                save_cache(self.cache)  # 每批落盘，断点续传
                done += len(chunk)
                print(f"      [AI] 已识别 {done}/{total} 个大文件夹...")
            except Exception as e:
                # 单批失败不阻断整体，跳过该批（保持 unknown）
                print(f"      [AI] 第 {i // batch_size + 1} 批失败，跳过：{type(e).__name__} {str(e)[:120]}")
                continue

    def analyze_one(self, path, name='', size_human=''):
        """对单个文件夹做「是什么 / 能否删除 / 删除影响」的分析（用户点按钮触发）。

        与批量识别共用磁盘缓存（键为 path，标记 ai_analyzed_one），命中即返回，省额度。
        返回结构化字段：summary / level(safe|caution|never) / deletable / impact / confidence。
        impact 是批量识别没有的字段——专门回答「删除会影响什么」。
        """
        if not path:
            raise ValueError('path 为空')
        cached = self.cache.get(path)
        if cached and cached.get('ai_analyzed_one'):
            return cached
        if not self.enabled or self.client is None:
            raise RuntimeError('AI 未启用（缺少 DeepSeek API Key）')
        prompt = (
            f"下面文件地址中，这个文件夹是干什么的？{path} （大小约 {size_human or '未知'}）\n\n"
            "请判断：\n"
            "1) summary：一句话说明这个文件夹是做什么用的、里面一般存放什么内容；\n"
            "2) level：删除它的风险——safe=可放心删除（多为缓存/临时/可重建），"
            "caution=可删但要先备份或退出对应软件，never=不建议/禁止删除（删了会导致软件或系统异常）；\n"
            "3) deletable：一句话给「能不能删除」的具体结论；\n"
            "4) impact：如果删除，会影响什么（如：某软件无法启动、某游戏进度丢失、系统功能异常等），"
            "不确定写「影响未知，建议先备份」；\n"
            "5) confidence：你判断的把握 high / medium / low。\n\n"
            '只输出严格 JSON：{"summary":"","level":"safe|caution|never",'
            '"deletable":"","impact":"","confidence":"high|medium|low"}'
        )
        try:
            resp = self._chat_completion([
                {"role": "system", "content": "你是 Windows 磁盘清理助手，只输出严格 JSON，不要多余文字。"},
                {"role": "user", "content": prompt},
            ])
        except Exception as e:
            name = type(e).__name__
            if 'Connection' in name or 'Timeout' in name:
                raise RuntimeError(
                    '连接 DeepSeek API 失败（网络/代理问题或 DeepSeek 临时不可用）。'
                    '若公司网络需代理，请在 .env 加一行 DEEPSEEK_PROXY=http://你的代理地址:端口 后重启；'
                    '也可能是 DeepSeek 服务器繁忙，请稍后重试。原始错误：' + name
                )
            raise
        text = resp.choices[0].message.content or ""
        data = self._parse_json(text)
        level = data.get('level', 'caution')
        if level not in ('safe', 'caution', 'never'):
            level = 'caution'
        conf = data.get('confidence', 'low')
        if conf not in ('high', 'medium', 'low'):
            conf = 'low'
        result = {
            'category': 'ai',
            'summary': (data.get('summary') or '').strip(),
            'level': level,
            'deletable': (data.get('deletable') or '').strip(),
            'impact': (data.get('impact') or '').strip(),
            'confidence': conf,
            'ai_analyzed_one': True,
        }
        # 合并写回，保留批量识别已有的 software 等字段
        merged = dict(self.cache.get(path, {}))
        merged.update(result)
        self.cache[path] = merged
        save_cache(self.cache)
        return merged

    @staticmethod
    def _parse_json(text):
        try:
            start = text.find('{')
            end = text.rfind('}')
            if start >= 0 and end > start:
                return json.loads(text[start:end + 1])
        except Exception:
            pass
        return {}

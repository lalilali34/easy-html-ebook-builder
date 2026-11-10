#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_client.py — OpenAI 兼容接口客户端（DeepSeek / OpenAI / 任意兼容网关）
========================================================================

零第三方依赖：只用 urllib。不装 requests 也能跑。

配置来源（优先级从高到低）：
  1. 构造参数
  2. 环境变量 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
  3. .env 文件（仓库根 `.env`，其次 `upstream/.env`）

.env 示例见仓库根 `.env.example`：

    LLM_BASE_URL=https://api.deepseek.com/v1
    LLM_API_KEY=sk-xxxxxxxx
    LLM_MODEL=deepseek-chat

用法：
    from llm_client import LLMClient
    c = LLMClient()
    data = c.chat_json(system="...", user="...")

命令行自检：
    python upstream/src/llm_client.py --ping
    python upstream/src/llm_client.py --ask "用一句话解释结构主义"

退出码：
    0  成功
    3  未配置 API Key
    5  调用失败
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


class LLMError(RuntimeError):
    pass


def load_dotenv(paths=None):
    """极简 .env 解析：KEY=VALUE，支持 # 注释与引号，不覆盖已有环境变量。"""
    if paths is None:
        paths = [ROOT / ".env", ROOT / "upstream" / ".env"]
    loaded = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
                loaded.append(k)
    return loaded


def extract_json(text):
    """从模型回复里抠出 JSON，容忍 ```json 围栏与前后散文。"""
    if not text or not text.strip():
        raise LLMError("模型返回了空内容")

    s = text.strip()

    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = s.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(s[start:i + 1])
                    except json.JSONDecodeError:
                        break

    raise LLMError("无法从回复中解析 JSON（前 200 字）：%s" % s[:200])


class LLMClient(object):
    def __init__(self, base_url=None, api_key=None, model=None,
                 timeout=180, max_retries=3, temperature=0.3):
        load_dotenv()
        self.base_url = (base_url
                         or os.environ.get("LLM_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = (api_key
                        or os.environ.get("LLM_API_KEY")
                        or os.environ.get("OPENAI_API_KEY")
                        or "").strip()
        self.model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature

    # ---------------------------------------------------------------- 状态

    def available(self):
        return bool(self.api_key)

    def describe(self):
        masked = ("%s...%s" % (self.api_key[:6], self.api_key[-4:])
                  if len(self.api_key) > 12 else "(未配置)")
        return "base_url=%s model=%s key=%s" % (self.base_url, self.model, masked)

    # ---------------------------------------------------------------- 调用

    def chat(self, system, user, temperature=None, max_tokens=None):
        if not self.api_key:
            raise LLMError(
                "未配置 API Key。请在仓库根创建 .env（参考 .env.example）：\n"
                "  LLM_BASE_URL=https://api.deepseek.com/v1\n"
                "  LLM_API_KEY=sk-xxxx\n"
                "  LLM_MODEL=deepseek-chat")

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature if temperature is None else temperature,
            "stream": False,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens

        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        url = self.base_url + "/chat/completions"

        last_err = None
        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", "Bearer " + self.api_key)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                choices = payload.get("choices") or []
                if not choices:
                    raise LLMError("接口返回无 choices：%s"
                                   % json.dumps(payload, ensure_ascii=False)[:300])
                return choices[0]["message"]["content"]
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                last_err = "HTTP %d: %s" % (e.code, detail)
                # 鉴权/参数错误不重试
                if e.code in (400, 401, 403, 404, 422):
                    raise LLMError(last_err)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = "%s: %s" % (type(e).__name__, e)
            except LLMError:
                raise

            if attempt < self.max_retries:
                wait = min(2 ** attempt, 10)
                time.sleep(wait)

        raise LLMError("调用失败（重试 %d 次后放弃）：%s" % (self.max_retries, last_err))

    def chat_json(self, system, user, **kwargs):
        return extract_json(self.chat(system, user, **kwargs))


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="OpenAI 兼容 LLM 客户端自检")
    ap.add_argument("--ping", action="store_true", help="检查配置并发一次最小请求")
    ap.add_argument("--ask", help="单轮提问")
    ap.add_argument("--model", help="覆盖模型名")
    ap.add_argument("--base-url", help="覆盖 base_url")
    args = ap.parse_args(argv)

    client = LLMClient(base_url=args.base_url, model=args.model)
    print("[config] " + client.describe(), flush=True)

    if not client.available():
        print("[FAIL] 未找到 API Key。复制 .env.example 为 .env 并填入 key。",
              file=sys.stderr)
        return 3

    try:
        if args.ping:
            out = client.chat("你是一个只回显的回声器。", "请只回复两个字符：OK")
            print("[ok] " + out.strip()[:100])
            return 0
        if args.ask:
            print(client.chat("你是严谨的中文技术助手。", args.ask))
            return 0
    except LLMError as e:
        print("[FAIL] " + str(e), file=sys.stderr)
        return 5

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

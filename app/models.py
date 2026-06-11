import base64
import io
import json
import time

import requests
from PIL import Image, ImageOps

from app.config import CONFIG, is_gemini_3


def extract_sources(obj, limit=8):
    """Collect source URLs from provider-specific citation/grounding metadata."""
    found = []
    seen = set()

    def add(url, title=""):
        if not isinstance(url, str):
            return
        url = url.strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            return
        seen.add(url)
        title = title.strip() if isinstance(title, str) else ""
        found.append({"title": title, "url": url})

    def walk(value):
        if len(found) >= limit:
            return
        if isinstance(value, dict):
            title = (
                value.get("title")
                or value.get("site_title")
                or value.get("domain")
                or value.get("name")
                or ""
            )
            for key in ("url", "uri"):
                add(value.get(key), title)
            citation = value.get("url_citation")
            if isinstance(citation, dict):
                add(citation.get("url"), citation.get("title") or title)
            web = value.get("web")
            if isinstance(web, dict):
                add(web.get("uri") or web.get("url"), web.get("title") or title)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(obj)
    return found[:limit]


def append_sources(text, sources):
    if not sources:
        return text
    lines = ["", "", "来源："]
    for i, source in enumerate(sources, 1):
        title = source["title"] or source["url"]
        lines.append(f"{i}. [{title}]({source['url']})")
    return text.rstrip() + "\n".join(lines)


def attachment_overview(files):
    if not files:
        return ""
    lines = ["本次问题包含以下附件，请在回答时结合这些附件："]
    for f in files:
        if f["type"] == "image":
            lines.append(f"- 图片：{f['name']}")
        elif f["type"] == "text_file":
            text_len = len(f.get("text", ""))
            lines.append(f"- 文档：{f['name']}（已提取约 {text_len} 字文本）")
    return "\n".join(lines)


def compress_image_for_responses(file_info, max_side=1280, max_bytes=1_200_000):
    """Compress uploaded image data before sending it through Responses API gateways."""
    raw = base64.b64decode(file_info["base64"])
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")

    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    for quality in (82, 74, 66, 58):
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        data = out.getvalue()
        if len(data) <= max_bytes or quality == 58:
            return {
                "mime_type": "image/jpeg",
                "base64": base64.b64encode(data).decode("ascii"),
            }


def gpt_image_budget(prompt, system, files):
    text_bytes = len((system + "\n" + prompt).encode("utf-8"))
    if files:
        for f in files:
            if f["type"] == "text_file":
                text_bytes += len(f.get("text", "").encode("utf-8"))
    image_count = sum(1 for f in files or [] if f["type"] == "image")
    if text_bytes > 40_000:
        return 768, max(220_000, 650_000 // max(image_count, 1))
    if text_bytes > 16_000:
        return 960, max(350_000, 900_000 // max(image_count, 1))
    return 1280, max(500_000, 1_200_000 // max(image_count, 1))


def build_gemini_url(cfg):
    base = cfg.get("base_url", "https://generativelanguage.googleapis.com").rstrip("/")
    if base.endswith(":generateContent"):
        return base
    return f"{base}/v1beta/models/{cfg['model']}:generateContent"


def build_claude_url(cfg):
    base = cfg.get("base_url", "https://api.anthropic.com").rstrip("/")
    if base.endswith("/messages") or base.endswith("/v1/messages"):
        return base
    return f"{base}/v1/messages"


# ===== 格式A1：OpenAI Chat Completions（DeepSeek / Qwen）=====
def call_openai_style(name, prompt, system="你是严谨的科研助手，请用中文回答。", stop_flag=None, files=None, enable_search=False):
    if stop_flag and stop_flag.is_set():
        return f"[{name}] 已中止", {"has_thought": False}
    cfg = CONFIG[name]
    url = cfg["base_url"]
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json"
    }

    # 构建 messages content
    if files:
        overview = attachment_overview(files)
        user_content = []
        # DeepSeek 不支持 image_url，图片转文本提示
        if name == "deepseek":
            prompt_parts = [prompt]
            if overview:
                prompt_parts.append(f"\n\n{overview}")
            for f in files:
                if f["type"] == "text_file":
                    prompt_parts.append(f"\n\n--- 以下为附件「{f['name']}」的完整内容 ---\n{f['text']}\n--- 附件结束 ---")
                elif f["type"] == "image":
                    prompt_parts.append(f"\n\n[图片附件: {f['name']}，DeepSeek 无法直接查看图片，请根据文字描述回答。]")
            data = {
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": "".join(prompt_parts)}
                ]
            }
        else:
            prompt_text = prompt
            if overview:
                prompt_text = f"{prompt}\n\n{overview}"
            user_content.append({"type": "text", "text": prompt_text})
            image_count = sum(1 for f in files if f["type"] == "image")
            image_max_bytes = max(500_000, 1_200_000 // max(image_count, 1))
            for f in files:
                if f["type"] == "image":
                    image_payload = compress_image_for_responses(
                        f,
                        max_side=1280,
                        max_bytes=image_max_bytes,
                    )
                    user_content.append({"type": "text", "text": f"下面这张图片是附件「{f['name']}」："})
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{image_payload['mime_type']};base64,{image_payload['base64']}"}
                    })
                elif f["type"] == "text_file":
                    user_content.append({"type": "text", "text": f"\n\n--- 以下为附件「{f['name']}」的完整内容 ---\n{f['text']}\n--- 附件结束 ---"})
            data = {
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content}
                ]
            }
    else:
        data = {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ]
        }

    if name == "deepseek":
        # DeepSeek 默认开启思考（reasoning_effort=high，对齐 v1）
        data["reasoning_effort"] = "high"

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=60)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        body = resp.json()
        sources = extract_sources(body)
        msg = body["choices"][0]["message"]
        has_thought = bool(msg.get("reasoning_content"))
        text = msg.get("content") or msg.get("reasoning_content", "")
        return append_sources(text, sources), {"has_thought": has_thought}
    except requests.HTTPError as e:
        detail = e.response.text if e.response is not None else str(e)
        return f"[{name} 调用失败]: {str(e)}\n{detail}", {"has_thought": False}
    except Exception as e:
        return f"[{name} 调用失败]: {str(e)}", {"has_thought": False}


# ===== 格式A2：OpenAI Responses API（GPT）=====
def call_responses_style(name, prompt, system="你是严谨的科研助手，请用中文回答。", stop_flag=None, enable_search=False, files=None):
    if stop_flag and stop_flag.is_set():
        return f"[{name}] 已中止", {"has_thought": False}
    cfg = CONFIG[name]
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json"
    }

    # 构建 input content：文本 + 图片 / 附件
    if files:
        overview = attachment_overview(files)
        prompt_text = f"{prompt}\n\n{overview}" if overview else prompt
        user_content = [{"type": "input_text", "text": prompt_text}]
        gpt_max_side, gpt_max_bytes = gpt_image_budget(prompt, system, files)
        for f in files:
            if f["type"] == "image":
                image_payload = compress_image_for_responses(
                    f,
                    max_side=gpt_max_side,
                    max_bytes=gpt_max_bytes,
                )
                user_content.append({"type": "input_text", "text": f"下面这张图片是附件「{f['name']}」："})
                user_content.append({
                    "type": "input_image",
                    "image_url": f"data:{image_payload['mime_type']};base64,{image_payload['base64']}"
                })
            elif f["type"] == "text_file":
                user_content.append({"type": "input_text", "text": f"\n\n--- 以下为附件「{f['name']}」的完整内容 ---\n{f['text']}\n--- 附件结束 ---"})
        system_input = [{"role": "system", "content": [{"type": "input_text", "text": system}]}]
        user_input = [{"role": "user", "content": user_content}]
        data = {"model": cfg["model"], "input": system_input + user_input}
    else:
        data = {
            "model": cfg["model"],
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ]
        }
    if name == "gpt":
        if enable_search:
            data["tools"] = [{"type": "web_search"}]
        # GPT 默认高强度思考（reasoning.effort=high，对齐 v1；不传 summary 避免慢）
        data["reasoning"] = {"effort": "high"}
    if name == "qwen":
        if enable_search:
            data["tools"] = [{"type": "web_search"}]
        # Qwen 默认开启思考（DashScope OpenAI-compatible 顶层参数）
        data["enable_thinking"] = True

    payload_bytes = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    last_conn_error = None
    resp = None
    for conn_attempt in range(2):  # 代理不稳定，失败等 3 秒重试一次
        try:
            resp = requests.post(cfg["base_url"], headers=headers, json=data, timeout=120)
            resp.encoding = "utf-8"
            last_conn_error = None
            break
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ProxyError) as ce:
            last_conn_error = ce
            if conn_attempt == 0:
                time.sleep(3)
        except requests.HTTPError:
            break

    if resp is None:
        detail = str(last_conn_error) if last_conn_error else "未知连接错误"
        return f"[{name} 调用失败]: {detail}\npayload_bytes={payload_bytes}", {"has_thought": False}

    try:
        resp.raise_for_status()
        body = resp.json()
        sources = extract_sources(body)

        text_parts = []
        reasoning_summary = []
        for item in body.get("output", []):
            item_type = item.get("type", "")
            if item_type == "message":
                for c in item.get("content", []):
                    t = c.get("text") or c.get("output_text")
                    if not t and isinstance(c, dict):
                        # 有些响应把文字放在 content.parts 里
                        for part in c.get("parts") or []:
                            t = part.get("text") or part.get("output_text")
                            if t:
                                break
                    if t:
                        text_parts.append(t)
            elif item_type == "reasoning":
                for s in item.get("summary") or []:
                    if s.get("text"):
                        reasoning_summary.append(s["text"])

        # 补充扫描：检查顶层 output_text（某些 API 版本放在这里）
        if not text_parts and body.get("output_text"):
            text_parts.append(body["output_text"])

        # 兜底扫描：遍历 output 数组里所有可能藏文字的地方
        if not text_parts:
            for item in body.get("output", []):
                if isinstance(item, dict):
                    # 递归取所有可能的文本字段
                    for key in ("text", "output_text", "content"):
                        val = item.get(key)
                        if isinstance(val, str) and val.strip():
                            text_parts.append(val)
                        elif isinstance(val, list):
                            for sub in val:
                                if isinstance(sub, dict):
                                    t = sub.get("text") or sub.get("output_text")
                                    if t and isinstance(t, str) and t.strip():
                                        text_parts.append(t)

        # 终极兜底：递归扫描整个响应 JSON，捡捞任何长字符串
        if not text_parts and not reasoning_summary:
            def _deep_extract(obj):
                texts = []
                if isinstance(obj, str) and len(obj) > 20:
                    texts.append(obj)
                elif isinstance(obj, dict):
                    for v in obj.values():
                        texts.extend(_deep_extract(v))
                elif isinstance(obj, list):
                    for v in obj:
                        texts.extend(_deep_extract(v))
                return texts
            candidates = _deep_extract(body)
            # 取最长的几条（排除推理相关的）
            reasoning_tokens_val = body.get("usage", {}).get("output_tokens_details", {}).get("reasoning_tokens", 0)
            if reasoning_tokens_val > 0:
                text_parts = [c for c in candidates if "reasoning" not in c.lower()][:3] if candidates else []
            else:
                text_parts = candidates[:3] if candidates else []

        # 检测是否真的发生了思考
        has_thought = len(reasoning_summary) > 0
        if not has_thought:
            reasoning_tokens = body.get("usage", {}).get("output_tokens_details", {}).get("reasoning_tokens", 0)
            has_thought = reasoning_tokens > 0

        if text_parts:
            return append_sources("\n".join(text_parts), sources), {"has_thought": has_thought}
        if reasoning_summary:
            text = "[模型仅返回推理摘要]\n\n" + "\n\n".join(reasoning_summary)
            return append_sources(text, sources), {"has_thought": True}

        usage = body.get("usage", {})
        return (
            f"[{name} 返回为空] "
            f"reasoning_tokens={usage.get('output_tokens_details', {}).get('reasoning_tokens', 0)}"
        ), {"has_thought": has_thought}
    except requests.HTTPError as e:
        detail = e.response.text if e.response is not None else str(e)
        return (
            f"[{name} 调用失败]: {str(e)}\n"
            f"payload_bytes={payload_bytes}\n{detail}"
        ), {"has_thought": False}
    except Exception as e:
        return f"[{name} 调用失败]: {str(e)}\npayload_bytes={payload_bytes}", {"has_thought": False}


# ===== 格式C：Anthropic Messages API（Claude）=====
def call_claude(prompt, system="你是严谨的科研助手，请用中文回答。", stop_flag=None, files=None, enable_search=False):
    if stop_flag and stop_flag.is_set():
        return "[claude] 已中止", {"has_thought": False}
    cfg = CONFIG["claude"]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
        "anthropic-version": "2023-06-01",
    }

    overview = attachment_overview(files)
    prompt_text = f"{prompt}\n\n{overview}" if overview else prompt
    content = [{"type": "text", "text": prompt_text}]
    if files:
        image_count = sum(1 for f in files if f["type"] == "image")
        image_max_bytes = max(500_000, 1_200_000 // max(image_count, 1))
        for f in files:
            if f["type"] == "image":
                image_payload = compress_image_for_responses(
                    f,
                    max_side=1280,
                    max_bytes=image_max_bytes,
                )
                media_type = image_payload["mime_type"]
                if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                    media_type = "image/jpeg"
                content.append({"type": "text", "text": f"下面这张图片是附件「{f['name']}」："})
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_payload["base64"],
                    },
                })
            elif f["type"] == "text_file":
                content.append({
                    "type": "text",
                    "text": f"\n\n--- 以下为附件「{f['name']}」的完整内容 ---\n{f['text']}\n--- 附件结束 ---",
                })

    if enable_search:
        content.insert(
            0,
            {
                "type": "text",
                "text": "请优先基于可用的最新信息回答；如果当前 Claude 中转站不支持联网搜索，请明确说明无法实时检索。",
            },
        )

    # Claude 默认开启中等强度思考（budget_tokens=4096，对齐用户要求）
    data = {
        "model": cfg["model"],
        "system": system,
        "max_tokens": 12000,
        "messages": [{"role": "user", "content": content}],
        "thinking": {"type": "enabled", "budget_tokens": 4096},
    }

    payload_bytes = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    try:
        resp = requests.post(build_claude_url(cfg), headers=headers, json=data, timeout=120)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        try:
            body = resp.json()
        except ValueError:
            return (
                f"[claude 调用失败]: 响应不是 JSON\n"
                f"status_code={resp.status_code}\n"
                f"payload_bytes={payload_bytes}\n"
                f"{resp.text[:500]}"
            ), {"has_thought": False}
        sources = extract_sources(body)
        text_parts = []
        for part in body.get("content", []):
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                text_parts.append(part["text"])
        text = "\n".join(text_parts).strip()
        if not text:
            text = body.get("completion") or "[claude 返回为空]"
        return append_sources(text, sources), {"has_thought": False}
    except requests.HTTPError as e:
        detail = e.response.text if e.response is not None else str(e)
        return (
            f"[claude 调用失败]: {str(e)}\n"
            f"payload_bytes={payload_bytes}\n{detail}"
        ), {"has_thought": False}
    except Exception as e:
        return f"[claude 调用失败]: {str(e)}\npayload_bytes={payload_bytes}", {"has_thought": False}


# ===== 格式B：Google AI Studio（Gemini）=====
def call_gemini(prompt, system="你是严谨的科研助手，请用中文回答。", stop_flag=None, files=None, enable_search=False):
    if stop_flag and stop_flag.is_set():
        return "[gemini] 已中止", {"has_thought": False}
    cfg = CONFIG["gemini"]
    url = build_gemini_url(cfg)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": cfg["api_key"]
    }

    # 构建 parts：文本 + 图片/附件
    overview = attachment_overview(files)
    prompt_text = f"{prompt}\n\n{overview}" if overview else prompt
    parts = [{"text": prompt_text}]
    if files:
        for f in files:
            if f["type"] == "image":
                # 压缩后发给中转站
                compressed = compress_image_for_responses(f, max_side=1024, max_bytes=800_000)
                parts.append({"text": f"下面这张图片是附件「{f['name']}」："})
                parts.append({
                    "inline_data": {
                        "mime_type": compressed["mime_type"],
                        "data": compressed["base64"]
                    }
                })
            elif f["type"] == "text_file":
                parts.append({"text": f"\n\n--- 以下为附件「{f['name']}」的完整内容 ---\n{f['text']}\n--- 附件结束 ---"})

    # Gemini 默认开启思考：2.x 系列 thinkingBudget=-1，3.x 系列 thinkingBudget=8192（中等）
    if is_gemini_3(cfg.get("model", "")):
        _gem_budget = 8192
    else:
        _gem_budget = -1

    data = {
        "contents": [{"role": "user", "parts": parts}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {
            "thinkingConfig": {"thinkingBudget": _gem_budget}
        }
    }
    if enable_search:
        data["tools"] = [{"google_search": {}}]

    last_error = ""
    last_body = ""
    for attempt in range(2):  # 最多重试 1 次
        try:
            resp = requests.post(url, headers=headers, json=data, timeout=60)
            resp.encoding = "utf-8"
            if not resp.ok:
                last_body = resp.text[:500]
            resp.raise_for_status()
            body = resp.json()
            sources = extract_sources(body)
            candidate = body["candidates"][0]
            content_parts = candidate["content"]["parts"]
            # 思考检测：3.5 / 2.5 均支持
            # 方式1: parts 中的 thought 标记
            has_thought = any(p.get("thought") for p in content_parts)
            # 方式2: 3.5 的 thoughtSignature 元数据
            if not has_thought:
                ts = candidate.get("content", {}).get("thoughtSignature")
                has_thought = bool(ts)
            text = next(p["text"] for p in reversed(content_parts) if "text" in p)
            return append_sources(text, sources), {"has_thought": has_thought}
        except Exception as e:
            last_error = str(e)
            if attempt == 0 and "503" in last_error:
                time.sleep(2)
                continue
            break

    detail = f" 响应: {last_body}" if last_body else ""
    return f"[gemini 调用失败]: {last_error}{detail}", {"has_thought": False}


# ===== 统一调用入口 =====
def call(name, prompt, system="你是严谨的科研助手，请用中文回答。", stop_flag=None, enable_search=False, files=None):
    if name == "gemini":
        return call_gemini(prompt, system, stop_flag, files=files, enable_search=enable_search)
    elif name == "claude":
        return call_claude(prompt, system, stop_flag, files=files, enable_search=enable_search)
    elif name == "gpt":
        return call_responses_style(name, prompt, system, stop_flag, enable_search=enable_search, files=files)
    elif name == "qwen":
        return call_responses_style(name, prompt, system, stop_flag, enable_search=enable_search, files=files)
    else:
        return call_openai_style(name, prompt, system, stop_flag, files=files)

"""
模型调用模块 — 统一封装各 AI 提供商的 API 差异
- call() 是唯一对外入口，根据 model name 路由到对应协议函数
- 支持文本 / 图片 / 文档附件，自动压缩图片以控制 token 开销
- 各函数返回 (text, meta_dict) 二元组，meta 中 has_thought 标记是否触发了思考链
"""
import base64
import io
import json
import time

import requests
from PIL import Image, ImageOps

from app.config import CONFIG, is_gemini_3


# ===== 共享模板与 helper =====

TEXT_FILE_TEMPLATE = "\n\n--- 以下为附件「{name}」的完整内容 ---\n{text}\n--- 附件结束 ---"
IMAGE_LABEL_TEMPLATE = "下面这张图片是附件「{name}」："


def _check_stop(name, stop_flag):
    """返回中止元组（如已请求停止），否则返回 None。"""
    if stop_flag and stop_flag.is_set():
        return f"[{name}] 已中止", {"has_thought": False}
    return None


def _image_budget_per_image(image_count):
    """单张图片的字节预算，Qwen / Claude / GPT 1280 档共用。"""
    return max(500_000, 1_200_000 // max(image_count, 1))


def _count_images(files):
    return sum(1 for f in (files or []) if f["type"] == "image")


def _prepare_prompt_with_overview(prompt, files):
    """拼接 prompt 与附件概览，返回 (prompt_text, overview_string)。"""
    overview = attachment_overview(files)
    prompt_text = f"{prompt}\n\n{overview}" if overview else prompt
    return prompt_text, overview


def _bearer_headers(api_key, extra=None):
    """构建 Authorization: Bearer 请求头，可选合并额外字段。"""
    h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _post_api(url, headers, data, timeout=60):
    """通用 POST → 编码 → 状态检查 → JSON 解析链。
    成功返回解析后的 JSON body，失败抛出异常（由调用方 try/except 包装）。"""
    resp = requests.post(url, headers=headers, json=data, timeout=timeout)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.json()


# ===== 引用来源提取 =====

def extract_sources(obj, limit=8):
    """从提供商各异的响应 JSON 中递归收集引用来源 URL。
    不同提供商把 citation 放在完全不同的字段名下（url、uri、url_citation、web 等），
    因此只能递归遍历整个响应对象，按启发式规则提取。"""
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


# ===== 图片压缩 =====

def compress_image_for_responses(file_info, max_side=1280, max_bytes=1_200_000):
    """压缩图片以控制 API 请求体积。
    多模型 API（尤其中转站）对 payload 大小敏感，超大会超时或被拒绝。
    策略：先缩放到 max_side，再逐步降低 JPEG quality 直到满足 max_bytes。"""
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
    """根据文本上下文长度动态调整图片压缩参数。
    GPT Responses API 对总 payload 有隐性限制，文本越长就需要图片越小，
    因此按文本字节数分档返回不同的 max_side 和 max_bytes。"""
    text_bytes = len((system + "\n" + prompt).encode("utf-8"))
    if files:
        for f in files:
            if f["type"] == "text_file":
                text_bytes += len(f.get("text", "").encode("utf-8"))
    image_count = _count_images(files)
    if text_bytes > 40_000:
        return 768, max(220_000, 650_000 // max(image_count, 1))
    if text_bytes > 16_000:
        return 960, max(350_000, 900_000 // max(image_count, 1))
    return 1280, _image_budget_per_image(image_count)


# ===== URL 构建 =====

def build_gemini_url(cfg):
    """构建 Gemini API 完整端点 URL。
    用户配置的 base_url 可能是裸域名（如 googleapis.com）或已拼好的端点，
    此函数统一归一化为 :generateContent 端点。"""
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
    """OpenAI Chat Completions 协议调用。
    服务于 DeepSeek 和 Qwen：DeepSeek 不支持 image_url，图片附件降级为文字描述；
    Qwen 支持多模态，图片以 image_url base64 内联发送。"""
    stopped = _check_stop(name, stop_flag)
    if stopped:
        return stopped

    cfg = CONFIG[name]
    headers = _bearer_headers(cfg["api_key"])

    if files:
        prompt_text, overview = _prepare_prompt_with_overview(prompt, files)

        if name == "deepseek":
            prompt_parts = [prompt]
            if overview:
                prompt_parts.append(f"\n\n{overview}")
            for f in files:
                if f["type"] == "text_file":
                    prompt_parts.append(TEXT_FILE_TEMPLATE.format(name=f["name"], text=f["text"]))
                elif f["type"] == "image":
                    prompt_parts.append(
                        f"\n\n[图片附件: {f['name']}，DeepSeek 无法直接查看图片，请根据文字描述回答。]"
                    )
            user_content = "".join(prompt_parts)
        else:
            user_content = [{"type": "text", "text": prompt_text}]
            img_budget = _image_budget_per_image(_count_images(files))
            for f in files:
                if f["type"] == "image":
                    image_payload = compress_image_for_responses(f, max_side=1280, max_bytes=img_budget)
                    user_content.append({"type": "text", "text": IMAGE_LABEL_TEMPLATE.format(name=f["name"])})
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{image_payload['mime_type']};base64,{image_payload['base64']}"}
                    })
                elif f["type"] == "text_file":
                    user_content.append({"type": "text", "text": TEXT_FILE_TEMPLATE.format(name=f["name"], text=f["text"])})

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
        data["reasoning_effort"] = "high"

    try:
        body = _post_api(cfg["base_url"], headers, data, timeout=60)
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


# ===== 格式A2：OpenAI Responses API（GPT / Qwen）=====

def call_responses_style(name, prompt, system="你是严谨的科研助手，请用中文回答。", stop_flag=None, enable_search=False, files=None):
    stopped = _check_stop(name, stop_flag)
    if stopped:
        return stopped

    cfg = CONFIG[name]
    headers = _bearer_headers(cfg["api_key"])

    if files:
        prompt_text, _ = _prepare_prompt_with_overview(prompt, files)
        user_content = [{"type": "input_text", "text": prompt_text}]
        gpt_max_side, gpt_max_bytes = gpt_image_budget(prompt, system, files)
        for f in files:
            if f["type"] == "image":
                image_payload = compress_image_for_responses(f, max_side=gpt_max_side, max_bytes=gpt_max_bytes)
                user_content.append({"type": "input_text", "text": IMAGE_LABEL_TEMPLATE.format(name=f["name"])})
                user_content.append({
                    "type": "input_image",
                    "image_url": f"data:{image_payload['mime_type']};base64,{image_payload['base64']}"
                })
            elif f["type"] == "text_file":
                user_content.append({"type": "input_text", "text": TEXT_FILE_TEMPLATE.format(name=f["name"], text=f["text"])})
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
        data["reasoning"] = {"effort": "high"}
    if name == "qwen":
        if enable_search:
            data["tools"] = [{"type": "web_search"}]
        data["enable_thinking"] = True

    payload_bytes = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    last_conn_error = None
    resp = None
    for conn_attempt in range(2):
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

        if not text_parts and body.get("output_text"):
            text_parts.append(body["output_text"])

        if not text_parts:
            for item in body.get("output", []):
                if isinstance(item, dict):
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
            reasoning_tokens_val = body.get("usage", {}).get("output_tokens_details", {}).get("reasoning_tokens", 0)
            if reasoning_tokens_val > 0:
                text_parts = [c for c in candidates if "reasoning" not in c.lower()][:3] if candidates else []
            else:
                text_parts = candidates[:3] if candidates else []

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
    stopped = _check_stop("claude", stop_flag)
    if stopped:
        return stopped

    cfg = CONFIG["claude"]
    headers = _bearer_headers(cfg["api_key"], extra={"anthropic-version": "2023-06-01"})

    prompt_text, _ = _prepare_prompt_with_overview(prompt, files)
    content = [{"type": "text", "text": prompt_text}]
    if files:
        img_budget = _image_budget_per_image(_count_images(files))
        for f in files:
            if f["type"] == "image":
                image_payload = compress_image_for_responses(f, max_side=1280, max_bytes=img_budget)
                media_type = image_payload["mime_type"]
                if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                    media_type = "image/jpeg"
                content.append({"type": "text", "text": IMAGE_LABEL_TEMPLATE.format(name=f["name"])})
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_payload["base64"],
                    },
                })
            elif f["type"] == "text_file":
                content.append({"type": "text", "text": TEXT_FILE_TEMPLATE.format(name=f["name"], text=f["text"])})

    if enable_search:
        content.insert(
            0,
            {
                "type": "text",
                "text": "请优先基于可用的最新信息回答；如果当前 Claude 中转站不支持联网搜索，请明确说明无法实时检索。",
            },
        )

    data = {
        "model": cfg["model"],
        "system": system,
        "max_tokens": 12000,
        "messages": [{"role": "user", "content": content}],
        "thinking": {"type": "enabled", "budget_tokens": 4096},
    }

    payload_bytes = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    try:
        body = _post_api(build_claude_url(cfg), headers, data, timeout=120)
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
    stopped = _check_stop("gemini", stop_flag)
    if stopped:
        return stopped

    cfg = CONFIG["gemini"]
    url = build_gemini_url(cfg)
    headers = {"Content-Type": "application/json", "x-goog-api-key": cfg["api_key"]}

    prompt_text, _ = _prepare_prompt_with_overview(prompt, files)
    parts = [{"text": prompt_text}]
    if files:
        for f in files:
            if f["type"] == "image":
                compressed = compress_image_for_responses(f, max_side=1024, max_bytes=800_000)
                parts.append({"text": IMAGE_LABEL_TEMPLATE.format(name=f["name"])})
                parts.append({
                    "inline_data": {
                        "mime_type": compressed["mime_type"],
                        "data": compressed["base64"]
                    }
                })
            elif f["type"] == "text_file":
                parts.append({"text": TEXT_FILE_TEMPLATE.format(name=f["name"], text=f["text"])})

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
    for attempt in range(2):
        try:
            body = _post_api(url, headers, data, timeout=60)
            sources = extract_sources(body)
            candidate = body["candidates"][0]
            content_parts = candidate["content"]["parts"]
            has_thought = any(p.get("thought") for p in content_parts)
            if not has_thought:
                ts = candidate.get("content", {}).get("thoughtSignature")
                has_thought = bool(ts)
            text = next(p["text"] for p in reversed(content_parts) if "text" in p)
            return append_sources(text, sources), {"has_thought": has_thought}
        except requests.HTTPError as e:
            last_error = str(e)
            if e.response is not None:
                last_error += f" 响应: {e.response.text[:500]}"
            if attempt == 0 and "503" in last_error:
                time.sleep(2)
                continue
            break
        except Exception as e:
            last_error = str(e)
            break

    return f"[gemini 调用失败]: {last_error}", {"has_thought": False}


# ===== 统一调用入口 =====

def call(name, prompt, system="你是严谨的科研助手，请用中文回答。", stop_flag=None, enable_search=False, files=None):
    """统一调用入口：根据模型名称路由到对应协议函数。
    - gemini → Google Generative AI 协议
    - claude → Anthropic Messages 协议
    - gpt/qwen → OpenAI Responses API 协议
    - 其他（deepseek 等）→ OpenAI Chat Completions 协议
    """
    if name == "gemini":
        return call_gemini(prompt, system, stop_flag, files=files, enable_search=enable_search)
    elif name == "claude":
        return call_claude(prompt, system, stop_flag, files=files, enable_search=enable_search)
    elif name in ("gpt", "qwen"):
        return call_responses_style(name, prompt, system, stop_flag, enable_search=enable_search, files=files)
    else:
        return call_openai_style(name, prompt, system, stop_flag, files=files)

import concurrent.futures
import queue
import threading
import time

from app.config import StopFlag
from app.models import call


def _call_with_heartbeat(name, fn, log_queue, stop_flag, interval=5):
    """心跳包装：启动后台线程执行 fn()，每 interval 秒汇报耗时。
    fn() 返回 (text, meta_dict)。
    返回 (text, meta, elapsed_seconds)。"""
    t0 = time.time()
    result_box = {}

    def runner():
        result_box["v"] = fn()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    while t.is_alive():
        t.join(timeout=interval)
        if t.is_alive():
            log_queue.put_nowait(f"**{name.upper()}** — ⏳ 仍在工作中（已耗时 {int(time.time()-t0)}s）")
        if stop_flag and stop_flag.is_set():
            break
    result = result_box.get("v", (f"[{name}] 已中止", {"has_thought": False}))
    return result[0], result[1], int(time.time() - t0)


def _thought_tag(meta):
    """根据 API 返回的 meta 生成真实的思考检测标签"""
    if meta.get("has_thought"):
        return "🗩 检测到思考"
    return ""


# ===== 交叉检查（完全不碰 st.*）=====
def cross_check(question, answers: dict, stop_flag=None, log_queue=None, force_search=False):
    revised = {}

    def check_one(name):
        if stop_flag and stop_flag.is_set():
            return name, f"[{name}] 已中止"
        others = {k: v for k, v in answers.items() if k != name}
        other_text = "\n\n".join([f"【{k.upper()} 的回答】\n{v}" for k, v in others.items()])
        prompt = (
            f"以下是针对同一个问题，其他AI模型给出的独立回答：\n\n{other_text}\n\n"
            f"原始问题：{question}\n\n"
            f"你之前的回答是：\n{answers[name]}\n\n"
            f"请参考上面其他模型的观点，检查你的回答是否有遗漏、错误或可以补充的地方。"
            f"如果你认为原回答已经准确，请直接输出原回答；如果需要修订，请输出修订后的版本。"
            f"不需要解释修改原因，直接给出最终回答即可。"
        )
        if log_queue:
            log_queue.put_nowait(f"**{name.upper()}** — 交叉检查中...")
        text, meta, elapsed = _call_with_heartbeat(
            name,
            lambda: call(name, prompt, stop_flag=stop_flag, enable_search=force_search),
            log_queue or queue.Queue(),
            stop_flag
        )
        thought_tag = _thought_tag(meta)
        # 如果模型推理了但输出为空，则保留原始回答
        if ("返回为空" in str(text) or "调用失败" in str(text)) and "已中止" not in str(text):
            if log_queue:
                log_queue.put_nowait(f"**{name.upper()}** — 检查输出为空，保留原始回答")
            text = answers[name]  # 兜底：用原始回答
        if log_queue:
            log_queue.put_nowait(
                f"**{name.upper()}** — 检查完成 ✓（{elapsed}s）{thought_tag}"
            )
        return name, text

    model_names = ", ".join(n.upper() for n in answers)
    if log_queue:
        log_queue.put_nowait(f"**SYSTEM** — {model_names} 交叉检查中（并发）...")

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(check_one, n): n for n in answers}
        for future in concurrent.futures.as_completed(futures):
            name, result = future.result()
            revised[name] = result

    return revised


# ===== 主流程（完全不碰 st.*）=====
def answer(question, stop_flag=None, log_queue=None, force_search=False, final_check=False, models=None, files=None):
    """models: 用户选择的模型列表，如 ["gpt", "gemini"]。默认 ["gpt", "gemini"]。"""

    def log(name, msg):
        if log_queue:
            log_queue.put_nowait(f"**{name.upper()}** — {msg}")

    if models is None:
        models = ["gpt", "gemini"]

    if not models:
        return {"错误": "未选择任何模型"}

    if force_search:
        log("system", "🌐 已开启强制联网")
    if final_check:
        log("system", "✅ 已开启最终查验")

    _logq = log_queue or queue.Queue()

    # ===== 第一阶段：选定模型并发独立回答 =====
    model_display = {"gpt": "GPT", "gemini": "Gemini", "qwen": "Qwen", "claude": "Claude"}
    log("system", f"📡 选定模型：{', '.join(model_display[m] for m in models)} — 并发回答中...")
    if files:
        def describe_file(f):
            if f["type"] == "image":
                approx_kb = int(len(f.get("base64", "")) * 3 / 4 / 1024)
                return f"{f['name']}(image, ~{approx_kb}KB)"
            return f"{f['name']}({f['type']})"

        file_summary = ", ".join(describe_file(f) for f in files)
        log("system", f"📎 附件: {file_summary}")
    else:
        log("system", "未检测到附件")
    first_round = {}

    def fetch(name):
        if stop_flag and stop_flag.is_set():
            return name, f"[{name}] 已中止"
        log(name, "独立回答中...")
        text, meta, elapsed = _call_with_heartbeat(
            name,
            lambda: call(name, question, stop_flag=stop_flag, files=files, enable_search=force_search),
            log_queue or queue.Queue(),
            stop_flag
        )
        thought_tag = _thought_tag(meta)
        log(name, f"完成 ✓（{elapsed}s）{thought_tag}")
        return name, text

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(fetch, n): n for n in models}
        for future in concurrent.futures.as_completed(futures):
            name, result = future.result()
            first_round[name] = result

    if stop_flag and stop_flag.is_set():
        return {f"{k.upper()} 初始回答": v for k, v in first_round.items()} | {"状态": "已中止"}

    # ===== 第二阶段：多模型则交叉检查 =====
    if len(models) >= 2:
        revised = cross_check(question, first_round, stop_flag=stop_flag, log_queue=log_queue, force_search=force_search)
        if stop_flag and stop_flag.is_set():
            return (
                {f"{k.upper()} 初始回答": v for k, v in first_round.items()} |
                {f"{k.upper()} 修订后": v for k, v in revised.items()} |
                {"状态": "已中止"}
            )
    else:
        revised = first_round  # 单模型无交叉检查

    # 构建返回结果
    result = {}
    for m in models:
        result[f"{model_display[m]} 初始回答"] = first_round[m]
    if len(models) >= 2:
        for m in models:
            result[f"{model_display[m]} 修订后"] = revised[m]

    if final_check:
        # ===== 第三阶段：DeepSeek 审查回答 =====
        log("deepseek", "📝 审查所有答案并输出最终结论...")

        today = time.strftime("%Y年%m月%d日")

        # 构建给 DeepSeek 的参考材料
        reference_parts = []
        if len(models) >= 2:
            for k, v in revised.items():
                if "已中止" in str(v) or "调用失败" in str(v):
                    v = first_round.get(k, v)
                reference_parts.append(f"【{k.upper()} 修订后回答】\n{v}")
        else:
            only_model = models[0]
            reference_parts.append(f"【{only_model.upper()} 回答】\n{first_round[only_model]}")

        final_prompt = (
            f"今天是{today}。\n\n"
            f"原始问题：{question}\n\n"
            + "\n\n".join(reference_parts)
            + f"\n\n你是最终审核者。请完成以下任务：\n"
            f"1. 以上回答可能涉及多个不同主题（如多条新闻）。请把每条独立主题都列出来，不要遗漏任何一个\n"
            f"2. 对比各回答在同一主题上的差异，找出事实矛盾（如存在）\n"
            f"3. 逐条给出最终答案，确保覆盖所有主题\n"
            f"4. 有明显的事实错误请修正；有争议请标注\n"
            f"注意：直接给清晰可读的最终答案，不要长篇分析，不要只挑一条。"
        )
        final, d_meta, d_elapsed = _call_with_heartbeat(
            "deepseek",
            lambda: call("deepseek", final_prompt, system="你是严谨的审稿助手，给出清晰直接的回答。", stop_flag=stop_flag),
            _logq,
            stop_flag
        )
        d_tag = _thought_tag(d_meta)
        log("deepseek", f"审查完成 ✓（{d_elapsed}s）{d_tag}")
        result["DeepSeek 最终综合"] = final
    else:
        log("system", "已跳过 DeepSeek 最终查验")

    return result

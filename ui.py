import base64
import io
import json
import os
import queue
import threading
from datetime import datetime

import fitz  # pymupdf
import streamlit as st
from docx import Document
from PIL import Image

from app.config import StopFlag, CONFIG, update_config
from app.workflow import answer


MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")


def load_history():
    """从磁盘加载历史记录"""
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(history):
    """保存历史记录到磁盘"""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def process_uploaded_files(uploaded_files):
    """将 Streamlit UploadedFile 列表转为统一的文件信息列表"""
    result = []
    if not uploaded_files:
        return result
    for uf in uploaded_files:
        raw = uf.getvalue()
        if not raw:
            st.toast(f"⚠️ {uf.name} 内容为空，已跳过")
            continue
        if len(raw) > MAX_FILE_SIZE:
            st.toast(f"⚠️ {uf.name} 超过 20MB，已跳过")
            continue
        mime = uf.type or ""
        name = uf.name.lower()
        # 图片
        is_image = mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))
        if not is_image:
            try:
                img = Image.open(io.BytesIO(raw))
                img.verify()
                is_image = True
            except Exception:
                is_image = False
        if is_image:
            result.append({
                "type": "image",
                "name": uf.name,
                "mime_type": mime if mime.startswith("image/") else "image/png",
                "base64": base64.b64encode(raw).decode("ascii"),
            })
        # PDF
        elif mime == "application/pdf" or name.endswith(".pdf"):
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
                # 截断过长的 PDF 文本，保留头尾
                max_chars = 80_000
                if len(text) > max_chars:
                    half = max_chars // 2
                    text = text[:half] + "\n\n…[中间内容已截断]…\n\n" + text[-half:]
                result.append({"type": "text_file", "name": uf.name, "text": text})
            except Exception:
                st.toast(f"⚠️ 无法解析 PDF: {uf.name}")
        # Word (.docx)
        elif name.endswith(".docx"):
            try:
                doc = Document(io.BytesIO(raw))
                text = "\n".join(p.text for p in doc.paragraphs)
                max_chars = 80_000
                if len(text) > max_chars:
                    half = max_chars // 2
                    text = text[:half] + "\n\n…[中间内容已截断]…\n\n" + text[-half:]
                result.append({"type": "text_file", "name": uf.name, "text": text})
            except Exception:
                st.toast(f"⚠️ 无法解析 Word: {uf.name}")
        # 旧版 Word (.doc) — python-docx 不兼容，尝试提取可读文本
        elif name.endswith(".doc"):
            try:
                # .doc 是二进制格式，跳过不可读字节，提取可见 ASCII/UTF-8 文本
                raw_text = raw.decode("utf-8", errors="ignore")
                visible = "".join(c for c in raw_text if c.isprintable() or c in "\n\r\t ")
                # 过滤掉太短的碎片，保留有意义段落
                lines = [l.strip() for l in visible.split("\n") if len(l.strip()) > 30]
                text = "\n".join(lines[:500])  # 最多 500 行
                if len(text) < 50:
                    raise ValueError("无法提取足够文本")
                result.append({"type": "text_file", "name": uf.name, "text": text})
            except Exception:
                st.toast(f"⚠️ .doc 格式兼容性有限，建议转为 .docx 或 PDF 后上传")
    return result

from app.pdf_export import export_pdf as _export_pdf


def main():
    st.set_page_config(page_title="科研工作流", page_icon="🔬", layout="wide")
    st.markdown(
        """
        <style>
        /* --- 选项按钮行：固定宽度+固定间距 --- */
        .st-key-option_controls [data-testid="stHorizontalBlock"] {
            gap: 8px !important;
        }
        /* 第1列：模型选择器 */
        .st-key-option_controls [data-testid="column"]:nth-child(1) {
            flex: 0 0 230px !important;
            max-width: 230px !important;
            min-width: 230px !important;
        }
        /* 第2列：联网搜索 */
        .st-key-option_controls [data-testid="column"]:nth-child(2) {
            flex: 0 0 160px !important;
            max-width: 160px !important;
            min-width: 160px !important;
        }
        /* 第3列：最终查验 */
        .st-key-option_controls [data-testid="column"]:nth-child(3) {
            flex: 0 0 160px !important;
            max-width: 160px !important;
            min-width: 160px !important;
        }
        /* 第4列：空白占位，吸收剩余空间 */
        .st-key-option_controls [data-testid="column"]:last-child {
            flex: 1 1 0 !important;
            min-width: 0 !important;
        }
        .st-key-option_controls [data-testid="stPopover"] button[data-testid="stPopoverButton"] {
            width: 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
        }
        .st-key-option_controls [data-testid="stPopover"] button[data-testid="stPopoverButton"],
        .st-key-force_search_btn button,
        .st-key-final_check_btn button {
            height: 40px !important;
            min-height: 40px !important;
            padding: 0 14px !important;
            border-radius: 8px !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-weight: 600 !important;
        }
        .st-key-force_search_btn button,
        .st-key-final_check_btn button {
            width: 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
        }
        .st-key-option_controls [data-testid="stPopover"] button[data-testid="stPopoverButton"] p,
        .st-key-force_search_btn button p,
        .st-key-final_check_btn button p {
            line-height: 1 !important;
            white-space: nowrap !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("🔬 多模型科研工作流")

    # ===== session_state 初始化 =====
    for key, default in [
        ("history", None), ("running", False), ("stop_flag", None),
        ("results", None), ("current_q", ""), ("pending_question", ""),
        ("log_queue", None), ("result_queue", None), ("log_lines", []),
        ("force_search", False), ("final_check", False),
        ("selected_models", ["gpt", "gemini"]),
        ("uploaded_files", None), ("file_info", []),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # 从磁盘加载历史记录（仅首次）
    if st.session_state.history is None:
        st.session_state.history = load_history()
        # 给没有 date 的旧记录补上时间戳（用 time 字段反推今天）
        dirty = False
        for item in st.session_state.history:
            if "date" not in item:
                item["date"] = "更早"
                dirty = True
        if dirty:
            save_history(st.session_state.history)

    # ===== 侧边栏：历史记录 =====
    with st.sidebar:
        st.markdown("""<style>
        /* --- 历史记录行布局 --- */
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
            align-items: center !important;
            gap: 4px !important;
            flex-wrap: nowrap !important;
        }
        /* 左侧列：允许缩小，不换行 */
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child {
            min-width: 0 !important;
            overflow: hidden !important;
            flex-shrink: 1 !important;
        }
        /* 左侧内容按钮：单行省略 */
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child button {
            display: block !important;
            text-align: left !important;
            padding-left: 8px !important;
            padding-right: 8px !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            width: 100% !important;
        }
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child button > div,
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child button > div > span {
            display: inline !important;
            text-align: left !important;
            width: auto !important;
            margin: 0 !important;
        }
        /* 右侧删除列：固定宽度、右对齐 */
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child {
            flex: 0 0 36px !important;
            max-width: 36px !important;
            min-width: 36px !important;
            display: flex !important;
            justify-content: flex-end !important;
        }
        /* 删除按钮：圆角正方形、居中 */
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 32px !important;
            height: 32px !important;
            min-width: 32px !important;
            min-height: 32px !important;
            max-width: 32px !important;
            max-height: 32px !important;
            padding: 0 !important;
            margin: 0 !important;
            border-radius: 8px !important;
            text-align: center !important;
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            flex-shrink: 0 !important;
        }
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button > div,
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button > div > span {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: auto !important;
            margin: 0 !important;
            padding: 0 !important;
            text-align: center !important;
        }
        /* 清空全部历史按钮 */
        section[data-testid="stSidebar"] button[kind="secondary"] {
            display: block !important;
            text-align: center !important;
        }
        </style>""", unsafe_allow_html=True)
        st.header("历史记录")
        if st.session_state.history:
            # 按日期分组
            from collections import OrderedDict
            date_groups = OrderedDict()
            for idx, item in enumerate(st.session_state.history):
                d = item.get("date", "")
                if d not in date_groups:
                    date_groups[d] = []
                date_groups[d].append((idx, item))

            for date_key, items in reversed(list(date_groups.items())):
                if date_key and date_key != "更早":
                    date_label = f"📅 {date_key}"
                else:
                    date_label = "📅 （无日期）"
                with st.expander(date_label, expanded=True):
                    for real_idx, item in reversed(items):
                        col_btn, col_del = st.columns([10, 1])
                        with col_btn:
                            label = f"[{item['time']}] {item['question']}"
                            if st.button(label, key=f"h_{real_idx}", use_container_width=True,
                                        disabled=item.get("results") is None,
                                        help=label):
                                st.session_state.results = item["results"]
                                st.session_state.current_q = item["question"]
                        with col_del:
                            if st.button("✕", key=f"del_{real_idx}", help="删除此条记录", use_container_width=True):
                                st.session_state.history.pop(real_idx)
                                save_history(st.session_state.history)
                                st.rerun()
        else:
            st.caption("暂无历史记录")
        if st.button("🗑 清空全部历史", use_container_width=True):
            st.session_state.history = []
            save_history([])
            st.rerun()

        # ===== 设置面板 =====
        with st.expander("⚙ 设置"):
            _display_names = {"gpt": "GPT", "gemini": "Gemini", "qwen": "Qwen", "claude": "Claude", "deepseek": "DeepSeek"}
            for provider in ["gpt", "gemini", "qwen", "claude", "deepseek"]:
                st.markdown(f"**{_display_names.get(provider, provider)}**")
                new_key = st.text_input(
                    "API Key", value=CONFIG[provider]["api_key"],
                    type="password", key=f"set_key_{provider}")
                new_url = st.text_input(
                    "Base URL", value=CONFIG[provider]["base_url"],
                    key=f"set_url_{provider}")
                new_model = st.text_input(
                    "Model", value=CONFIG[provider]["model"],
                    key=f"set_model_{provider}")
                if (new_key != CONFIG[provider]["api_key"] or
                        new_url != CONFIG[provider]["base_url"] or
                        new_model != CONFIG[provider]["model"]):
                    update_config(provider, "api_key", new_key)
                    update_config(provider, "base_url", new_url)
                    update_config(provider, "model", new_model)

    # ===== 文件上传 =====
    uploaded_files = st.file_uploader(
        "📎 上传文件（图片: JPG/PNG | 文档: PDF/DOC/DOCX）",
        type=["jpg", "jpeg", "png", "pdf", "doc", "docx"],
        accept_multiple_files=True,
        disabled=st.session_state.running,
        key="file_uploader",
    )

    if not st.session_state.running and uploaded_files:
        st.session_state.file_info = process_uploaded_files(uploaded_files)

    if st.session_state.get("file_info"):
        names = ", ".join(f["name"] for f in st.session_state.file_info)
        st.caption(f"📎 本次将发送 {len(st.session_state.file_info)} 个附件：{names}")
    elif uploaded_files:
        names = ", ".join(uf.name for uf in uploaded_files)
        st.caption(f"📎 已选择 {len(uploaded_files)} 个附件，但解析结果为空：{names}")
    else:
        st.caption("📎 当前没有待发送附件")

    # ===== 输入区 =====
    question = st.text_area(
        "输入科研问题",
        height=110,
        placeholder="例如：请分析 CRISPR-Cas9 的脱靶效应机理及改进策略",
        disabled=st.session_state.running,
    )

    with st.container(key="option_controls"):
        col_opts1, col_opts2, col_opts3, _ = st.columns([3, 2, 2, 10], gap="small")
        with col_opts1:
            # 弹出式模型选择
            models_available = ["gpt", "gemini", "qwen", "claude"]
            model_display = {"gpt": "GPT", "gemini": "Gemini", "qwen": "Qwen", "claude": "Claude"}
            selected = st.session_state.selected_models
            label_text = "🔢 " + ("未选择" if not selected else "+".join(model_display[m] for m in selected))
            with st.popover(label_text, disabled=st.session_state.running, use_container_width=True):
                st.caption("选择参与回答的模型")
                new_selection = []
                for m in models_available:
                    if st.checkbox(model_display[m], value=m in selected, key=f"model_cb_{m}", disabled=st.session_state.running):
                        new_selection.append(m)
                if new_selection != selected:
                    st.session_state.selected_models = new_selection
                    st.rerun()
        with col_opts2:
            search_type = "primary" if st.session_state.force_search else "secondary"
            if st.button(
                "🌐 联网搜索",
                type=search_type,
                use_container_width=True,
                disabled=st.session_state.running,
                key="force_search_btn",
            ):
                st.session_state.force_search = not st.session_state.force_search
                st.rerun()
        with col_opts3:
            final_check_type = "primary" if st.session_state.final_check else "secondary"
            if st.button(
                "🐋 最终查验",
                type=final_check_type,
                use_container_width=True,
                disabled=st.session_state.running,
                key="final_check_btn",
            ):
                st.session_state.final_check = not st.session_state.final_check
                st.rerun()
    force_search = st.session_state.force_search
    final_check = st.session_state.final_check

    export_ready = not st.session_state.running and st.session_state.results is not None

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        send_btn = st.button("🚀 发送", type="primary", use_container_width=True,
                             disabled=st.session_state.running)
    with col2:
        stop_btn = st.button("⏹ 停止", type="secondary", use_container_width=True,
                             disabled=not st.session_state.running)
    with col3:
        if export_ready:
            # 仅在结果变化时重新生成 PDF
            cache_key = st.session_state.current_q
            if st.session_state.get("_pdf_cache_key") != cache_key:
                st.session_state._pdf_cache = _export_pdf(st.session_state.current_q, st.session_state.results)
                st.session_state._pdf_cache_key = cache_key
            st.download_button(
                "📄 导出", data=st.session_state._pdf_cache, file_name=f"科研工作流_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf", type="secondary", use_container_width=True,
                disabled=st.session_state.running
            )
        else:
            st.button("📄 导出", type="secondary", use_container_width=True, disabled=True)

    # ===== 停止 =====
    if stop_btn and st.session_state.stop_flag:
        st.session_state.stop_flag.set()
        st.session_state.running = False
        st.session_state.pending_question = ""
        st.session_state.results = {"状态": "⏹ 已手动中止"}
        st.session_state.log_lines = []
        st.rerun()

    # ===== 发送：启动后台线程，只用 queue 通信，绝不注入 ctx =====
    if send_btn and question.strip():
        if uploaded_files:
            st.session_state.file_info = process_uploaded_files(uploaded_files)
        _files = st.session_state.get("file_info") or None

        st.session_state.running = True
        st.session_state.results = None
        st.session_state.log_lines = []
        st.session_state.pending_question = question.strip()
        st.session_state.current_q = question.strip()

        # 立即创建历史记录条目（结果就绪后再回填）
        now = datetime.now()
        q = question.strip()
        if not any(h["question"] == q and h.get("results") is None for h in st.session_state.history):
            st.session_state.history.append({
                "question": q,
                "results": None,
                "time": now.strftime("%H:%M"),
                "date": now.strftime("%Y-%m-%d"),
            })
            save_history(st.session_state.history)

        stop_flag = StopFlag()
        st.session_state.stop_flag = stop_flag

        log_q = queue.Queue()
        result_q = queue.Queue()
        st.session_state.log_queue = log_q
        st.session_state.result_queue = result_q

        # worker 里完全不碰任何 st.* API。
        _models = st.session_state.selected_models
        def worker():
            try:
                result = answer(
                    question.strip(),
                    stop_flag=stop_flag,
                    log_queue=log_q,
                    force_search=force_search,
                    final_check=final_check,
                    models=_models,
                    files=_files,
                )
            except Exception as e:
                result = {"错误": f"工作流异常: {e}"}

            if not stop_flag.is_set():
                result_q.put_nowait(result)

        t = threading.Thread(target=worker, daemon=True)
        t.start()  # ← 不调用 add_script_run_ctx，彻底隔离
        st.rerun()

    # ===== 运行中：fragment 轮询 queue，主线程负责写 session_state =====
    if st.session_state.running:
        @st.fragment(run_every=2)
        def progress_panel():
            log_q = st.session_state.log_queue
            result_q = st.session_state.result_queue

            # 把 queue 里的日志全部取出写入 session_state（主线程，安全）
            if log_q:
                while not log_q.empty():
                    try:
                        st.session_state.log_lines.append(log_q.get_nowait())
                    except Exception:
                        break

            # 检查结果是否就绪
            if result_q and not result_q.empty():
                try:
                    result = result_q.get_nowait()
                    st.session_state.results = result
                    st.session_state.running = False
                    st.rerun()
                    return
                except Exception:
                    pass

            lines = st.session_state.log_lines
            st.info("\n\n".join(lines[-6:]) if lines else "工作流启动中...")

        progress_panel()

    # ===== 回填历史 =====
    if (not st.session_state.running
            and st.session_state.results is not None
            and st.session_state.pending_question):
        q = st.session_state.pending_question
        filled = False
        for item in reversed(st.session_state.history):
            if item["question"] == q and item.get("results") is None:
                item["results"] = st.session_state.results
                filled = True
                break
        if not filled and not any(h["question"] == q for h in st.session_state.history):
            now = datetime.now()
            st.session_state.history.append({
                "question": q,
                "results": st.session_state.results,
                "time": now.strftime("%H:%M"),
                "date": now.strftime("%Y-%m-%d"),
            })
        save_history(st.session_state.history)
        st.session_state.pending_question = ""

    # ===== 结果展示 =====
    if st.session_state.results:
        # 运行日志（折叠面板，默认收起）
        if st.session_state.log_lines:
            with st.expander(
                f"📝 运行过程（{len(st.session_state.log_lines)} 条日志，最近：{st.session_state.log_lines[-1][:50]}...）",
                expanded=False
            ):
                st.caption("\n\n".join(st.session_state.log_lines))
        st.divider()
        if st.session_state.current_q:
            st.subheader(f"问题：{st.session_state.current_q}")

        results = st.session_state.results
        initial_keys = [k for k in results if "初始回答" in k]
        revised_keys = [k for k in results if "修订后" in k]
        ds_final = results.get("DeepSeek 最终综合")

        # 阶段一：初始回答（并排）
        if initial_keys:
            st.markdown("**📡 初始回答**")
            cols = st.columns(len(initial_keys))
            for i, key in enumerate(initial_keys):
                with cols[i]:
                    model_name = key.replace(" 初始回答", "")
                    with st.container(height=450, border=True):
                        st.caption(f"**{model_name}**")
                        st.markdown(results[key])

        # 阶段二：修订后回答（并排）
        if revised_keys:
            st.markdown("**🔄 交叉验证修订**")
            cols = st.columns(len(revised_keys))
            for i, key in enumerate(revised_keys):
                with cols[i]:
                    model_name = key.replace(" 修订后", "")
                    with st.container(height=450, border=True):
                        st.caption(f"**{model_name}**")
                        st.markdown(results[key])

        # 阶段三：DeepSeek 最终综合（默认展开）
        if ds_final:
            with st.expander("📋 DeepSeek 最终综合", expanded=True):
                st.markdown(ds_final)


if __name__ == "__main__":
    main()

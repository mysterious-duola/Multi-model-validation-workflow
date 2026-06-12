"""
Streamlit 主界面 — 应用入口（streamlit run ui.py）

薄编排层：负责页面配置、session_state 初始化、各 UI 区域的调用编排。
所有具体逻辑（CSS、历史、设置、文件处理、线程调度、结果展示）
均委托给 ui/ 子模块包。

后端逻辑（config / models / workflow）完全解耦，可独立测试和复用。
"""
import streamlit as st

from ui import (
    inject_styles,
    render_sidebar_history,
    render_settings_panel,
    process_uploaded_files,
    dispatch_question,
    render_progress_panel,
    render_results,
    render_export_button,
    backfill_history,
    load_history,
    save_history,
)


def main():
    st.set_page_config(page_title="科研工作流", page_icon="🔬", layout="wide")
    inject_styles()
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

    if st.session_state.history is None:
        st.session_state.history = load_history()
        dirty = False
        for item in st.session_state.history:
            if "date" not in item:
                item["date"] = "更早"
                dirty = True
        if dirty:
            save_history(st.session_state.history)

    # ===== 侧边栏 =====
    with st.sidebar:
        render_sidebar_history()

        with st.expander("⚙ 设置"):
            render_settings_panel()

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

    # ===== 选项工具栏 =====
    with st.container(key="option_controls"):
        col_opts1, col_opts2, col_opts3, _ = st.columns([3, 2, 2, 10], gap="small")
        with col_opts1:
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

    # ===== 操作按钮行 =====
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        send_btn = st.button("🚀 发送", type="primary", use_container_width=True,
                             disabled=st.session_state.running)
    with col2:
        stop_btn = st.button("⏹ 停止", type="secondary", use_container_width=True,
                             disabled=not st.session_state.running)
    with col3:
        render_export_button()

    # ===== 停止处理 =====
    if stop_btn and st.session_state.stop_flag:
        st.session_state.stop_flag.set()
        st.session_state.running = False
        st.session_state.pending_question = ""
        st.session_state.results = {"状态": "⏹ 已手动中止"}
        st.session_state.log_lines = []
        st.rerun()

    # ===== 发送处理 =====
    if send_btn and question.strip():
        if uploaded_files:
            st.session_state.file_info = process_uploaded_files(uploaded_files)
        dispatch_question(
            question=question.strip(),
            selected_models=st.session_state.selected_models,
            force_search=st.session_state.force_search,
            final_check=st.session_state.final_check,
            file_info=st.session_state.get("file_info") or None,
        )

    # ===== 运行中：fragment 轮询 =====
    if st.session_state.running:
        render_progress_panel()

    # ===== 历史回填 =====
    backfill_history()

    # ===== 结果展示 =====
    render_results()


if __name__ == "__main__":
    main()

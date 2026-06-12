"""结果展示、PDF 导出、历史回填"""
from datetime import datetime

import streamlit as st

from app.pdf_export import export_pdf as _export_pdf


def render_results():
    """渲染三阶段结果（初始回答 / 交叉修订 / DeepSeek 综合）。

    读取: session_state.results, .log_lines, .current_q
    """
    if not st.session_state.results:
        return

    if st.session_state.log_lines:
        with st.expander(
            f"📝 运行过程（{len(st.session_state.log_lines)} 条日志，"
            f"最近：{st.session_state.log_lines[-1][:50]}...）",
            expanded=False,
        ):
            st.caption("\n\n".join(st.session_state.log_lines))

    st.divider()
    if st.session_state.current_q:
        st.subheader(f"问题：{st.session_state.current_q}")

    results = st.session_state.results
    initial_keys = [k for k in results if "初始回答" in k]
    revised_keys = [k for k in results if "修订后" in k]
    ds_final = results.get("DeepSeek 最终综合")

    if initial_keys:
        st.markdown("**📡 初始回答**")
        cols = st.columns(len(initial_keys))
        for i, key in enumerate(initial_keys):
            with cols[i]:
                model_name = key.replace(" 初始回答", "")
                with st.container(height=450, border=True):
                    st.caption(f"**{model_name}**")
                    st.markdown(results[key])

    if revised_keys:
        st.markdown("**🔄 交叉验证修订**")
        cols = st.columns(len(revised_keys))
        for i, key in enumerate(revised_keys):
            with cols[i]:
                model_name = key.replace(" 修订后", "")
                with st.container(height=450, border=True):
                    st.caption(f"**{model_name}**")
                    st.markdown(results[key])

    if ds_final:
        with st.expander("📋 DeepSeek 最终综合", expanded=True):
            st.markdown(ds_final)


def render_export_button():
    """渲染导出按钮（结果就绪时可用，否则禁用）。

    放在按钮行的第三列中调用。
    读取: session_state.running, .results, .current_q
    """
    export_ready = not st.session_state.running and st.session_state.results is not None
    if export_ready:
        cache_key = st.session_state.current_q
        if st.session_state.get("_pdf_cache_key") != cache_key:
            st.session_state._pdf_cache = _export_pdf(
                st.session_state.current_q, st.session_state.results
            )
            st.session_state._pdf_cache_key = cache_key
        st.download_button(
            "📄 导出",
            data=st.session_state._pdf_cache,
            file_name=f"科研工作流_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf", type="secondary",
            use_container_width=True, disabled=st.session_state.running,
        )
    else:
        st.button("📄 导出", type="secondary",
                  use_container_width=True, disabled=True)


def backfill_history():
    """将结果回填到历史占位条目。

    在每次 rerun 中调用（非运行时、有结果、有待回填的问题时生效）。
    读取/写入: session_state.history, .pending_question, .results, .running
    """
    if (st.session_state.running
            or st.session_state.results is None
            or not st.session_state.pending_question):
        return

    from ui.ui_history import save_history

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

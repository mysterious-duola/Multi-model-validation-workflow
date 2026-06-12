"""后台任务调度 — worker 线程启动与 fragment 轮询"""
import queue
import threading
from datetime import datetime

import streamlit as st

from app.config import StopFlag
from app.workflow import answer
from ui.ui_history import save_history


def dispatch_question(question, selected_models, force_search, final_check,
                      file_info=None):
    """启动后台 worker 线程，设置 session_state 并创建历史占位。

    此函数会调用 st.rerun()，调用方不应再执行后续 UI 代码。

    Parameters
    ----------
    question : str — 已 strip 的问题文本
    selected_models : list[str] — 如 ["gpt", "gemini"]
    force_search : bool
    final_check : bool
    file_info : list[dict] | None — process_uploaded_files 的输出
    """
    st.session_state.running = True
    st.session_state.results = None
    st.session_state.log_lines = []
    st.session_state.pending_question = question
    st.session_state.current_q = question

    now = datetime.now()
    if not any(h["question"] == question and h.get("results") is None
               for h in st.session_state.history):
        st.session_state.history.append({
            "question": question,
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

    def worker():
        """后台线程：只通过 queue 通信，绝不碰 st.* API"""
        try:
            result = answer(
                question,
                stop_flag=stop_flag,
                log_queue=log_q,
                force_search=force_search,
                final_check=final_check,
                models=selected_models,
                files=file_info,
            )
        except Exception as e:
            result = {"错误": f"工作流异常: {e}"}

        if not stop_flag.is_set():
            result_q.put_nowait(result)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    st.rerun()


@st.fragment(run_every=2)
def render_progress_panel():
    """轻量级轮询：每 2 秒局部刷新，从 queue 取日志和结果。

    读取: session_state.log_queue, .result_queue, .log_lines
    写入: session_state.log_lines, .results, .running
    """
    log_q = st.session_state.log_queue
    result_q = st.session_state.result_queue

    if log_q:
        while not log_q.empty():
            try:
                st.session_state.log_lines.append(log_q.get_nowait())
            except Exception:
                break

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

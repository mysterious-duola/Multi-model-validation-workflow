"""历史记录管理 — 加载、保存、侧边栏渲染"""
import json
import os
from collections import OrderedDict

import streamlit as st

from ui.ui_styles import SIDEBAR_HISTORY_CSS

HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history.json")


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


def render_sidebar_history():
    """渲染侧边栏历史记录区域。

    必须在 st.sidebar 上下文内调用。
    读取: st.session_state.history
    写入: st.session_state.history, .results, .current_q（点击回填时）
    """
    st.markdown(SIDEBAR_HISTORY_CSS, unsafe_allow_html=True)
    st.header("历史记录")
    if st.session_state.history:
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
                        full_label = f"[{item['time']}] {item['question']}"
                        label = full_label if len(full_label) <= 40 else full_label[:37] + "..."
                        if st.button(label, key=f"h_{real_idx}", use_container_width=True,
                                     disabled=item.get("results") is None,
                                     help=full_label):
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

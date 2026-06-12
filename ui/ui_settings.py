"""设置面板 — 侧边栏 API Key / URL / Model 配置"""
import streamlit as st

from app.config import CONFIG, update_config

_DISPLAY_NAMES = {
    "gpt": "GPT", "gemini": "Gemini", "qwen": "Qwen",
    "claude": "Claude", "deepseek": "DeepSeek",
}
_PROVIDERS = ["gpt", "gemini", "qwen", "claude", "deepseek"]


def render_settings_panel():
    """渲染设置面板（必须在 st.expander 或 st.sidebar 上下文内调用）。

    读取: CONFIG[provider][field]
    写入: 通过 update_config() 持久化
    """
    for provider in _PROVIDERS:
        st.markdown(f"**{_DISPLAY_NAMES.get(provider, provider)}**")
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

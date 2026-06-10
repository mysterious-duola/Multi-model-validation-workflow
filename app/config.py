import os
from dotenv import load_dotenv

load_dotenv()


def _get(key, default=""):
    val = os.getenv(key, "")
    if not val:
        try:
            import streamlit as st
            val = st.secrets.get(key, default)
        except Exception:
            val = default
    return val


CONFIG = {
    "qwen": {
        "api_key": _get("QWEN_API_KEY"),
        "base_url": _get("QWEN_BASE_URL"),
        "model": _get("QWEN_MODEL", "qwen3.5-flash")
    },
    "deepseek": {
        "api_key": _get("DEEPSEEK_API_KEY"),
        "base_url": _get("DEEPSEEK_BASE_URL"),
        "model": _get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    },
    "gpt": {
        "api_key": _get("GPT_API_KEY"),
        "base_url": _get("GPT_BASE_URL"),
        "model": _get("GPT_MODEL", "gpt-5.4")
    },
    "gemini": {
        "api_key": _get("GEMINI_API_KEY"),
        "base_url": _get("GEMINI_BASE_URL"),
        "model": _get("GEMINI_MODEL", "gemini-2.5-flash")
    },
    "claude": {
        "api_key": _get("CLAUDE_API_KEY"),
        "base_url": _get("CLAUDE_BASE_URL"),
        "model": _get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    },
}


# ===== 停止标志 =====
class StopFlag:
    def __init__(self):
        self._stop = False

    def set(self):
        self._stop = True

    def is_set(self):
        return self._stop

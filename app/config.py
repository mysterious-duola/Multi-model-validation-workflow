import os
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    "qwen": {
        "api_key": os.getenv("QWEN_API_KEY", ""),
        "base_url": os.getenv("QWEN_BASE_URL", ""),
        "model": os.getenv("QWEN_MODEL", "qwen3.5-flash")
    },
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", ""),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    },
    "gpt": {
        "api_key": os.getenv("GPT_API_KEY", ""),
        "base_url": os.getenv("GPT_BASE_URL", ""),
        "model": os.getenv("GPT_MODEL", "gpt-5.4")
    },
    "gemini": {
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "base_url": os.getenv("GEMINI_BASE_URL", ""),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    },
    "claude": {
        "api_key": os.getenv("CLAUDE_API_KEY", ""),
        "base_url": os.getenv("CLAUDE_BASE_URL", ""),
        "model": os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
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

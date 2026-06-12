"""
配置管理模块
- 从 .env 加载各模型 API 密钥 / Base URL / Model 名称
- 支持 settings.json 持久化运行时修改（侧边栏设置面板）
- 提供 StopFlag 线程安全中止标志供 UI ↔ worker 通信
"""
import os, json
from dotenv import load_dotenv

load_dotenv()

# settings.json 放在项目根目录（app/ 的上一级），方便 UI 层和启动脚本直接访问
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "settings.json")

_PROVIDERS = ["qwen", "deepseek", "gpt", "gemini", "claude"]
_FIELDS = ["api_key", "base_url", "model"]
_ENV_PREFIX = {
    "qwen": "QWEN", "deepseek": "DEEPSEEK", "gpt": "GPT",
    "gemini": "GEMINI", "claude": "CLAUDE",
}
# 各模型的硬编码默认值，当 .env 和 settings.json 均未配置时生效
_DEFAULTS = {
    "qwen":     {"model": "qwen3.5-flash"},
    "deepseek": {"model": "deepseek-v4-flash"},
    "gpt":      {"model": "gpt-5.4"},
    "gemini":   {"model": "gemini-2.5-flash"},
    "claude":   {"model": "claude-haiku-4-5-20251001"},
}


def is_gemini_3(model_name):
    """识别模型是否为 Gemini 3.x 系列（支持独立多档思考强度）"""
    if not isinstance(model_name, str):
        return False
    name = model_name.lower()
    return "gemini-3" in name or "gemini3" in name or "gemini 3" in name


def _env_get(key, default=""):
    val = os.getenv(key, "")
    if not val:
        try:
            import streamlit as st
            # Streamlit Cloud 部署时，密钥存放在 secrets.toml 而非 .env，此处兼容
            val = st.secrets.get(key, default)
        except Exception:
            val = default
    return val


def _build_config():
    cfg = {}
    for provider in _PROVIDERS:
        prefix = _ENV_PREFIX[provider]
        cfg[provider] = {}
        for field in _FIELDS:
            env_key = f"{prefix}_{field.upper()}"
            default = _DEFAULTS.get(provider, {}).get(field, "")
            cfg[provider][field] = _env_get(env_key, default)
    return cfg


CONFIG = _build_config()


def load_settings():
    """从 settings.json 加载用户自定义配置，覆盖默认值"""
    if not os.path.exists(SETTINGS_FILE):
        return
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        for provider in _PROVIDERS:
            if provider in saved:
                for field in _FIELDS:
                    if field in saved[provider] and saved[provider][field]:
                        CONFIG[provider][field] = saved[provider][field]
    except Exception:
        pass


def save_settings():
    """将当前 CONFIG 保存到 settings.json"""
    data = {}
    for provider in _PROVIDERS:
        data[provider] = {}
        for field in _FIELDS:
            data[provider][field] = CONFIG[provider].get(field, "")
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def update_config(provider, field, value):
    """运行时修改配置并持久化"""
    if provider in CONFIG and field in CONFIG[provider]:
        CONFIG[provider][field] = value
        save_settings()


load_settings()


# ===== 停止标志 =====
class StopFlag:
    """线程安全中止标志。
    不用 threading.Event 是因为 worker 只在检查点轮询 is_set()，
    不需要阻塞等待，简单布尔值足够且更易序列化到 session_state。"""
    def __init__(self):
        self._stop = False

    def set(self):
        self._stop = True

    def is_set(self):
        return self._stop

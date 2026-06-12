"""
app 包 — 多模型科研工作流后端核心

模块职责划分：
  config.py     配置管理（.env / settings.json / StopFlag）
  models.py     模型 API 调用（GPT / Gemini / Claude / Qwen / DeepSeek）
  workflow.py   工作流编排（并发回答 → 交叉验证 → 最终综合）
  pdf_export.py PDF 报告导出（fpdf2 + 中文字体）
"""

"""文件上传处理 — 将 Streamlit UploadedFile 转为统一文件信息列表"""
import base64
import io

import fitz  # pymupdf
import streamlit as st
from docx import Document
from PIL import Image

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def process_uploaded_files(uploaded_files):
    """将 Streamlit UploadedFile 列表转为统一的文件信息列表。
    输出格式：
    - 图片: {"type": "image", "name": ..., "mime_type": ..., "base64": ...}
    - 文档: {"type": "text_file", "name": ..., "text": ...}
    自动检测文件类型，PDF/Word 提取纯文本，超长内容截断头尾。"""
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
        elif mime == "application/pdf" or name.endswith(".pdf"):
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
                max_chars = 80_000
                if len(text) > max_chars:
                    half = max_chars // 2
                    text = text[:half] + "\n\n…[中间内容已截断]…\n\n" + text[-half:]
                result.append({"type": "text_file", "name": uf.name, "text": text})
            except Exception:
                st.toast(f"⚠️ 无法解析 PDF: {uf.name}")
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
        elif name.endswith(".doc"):
            try:
                raw_text = raw.decode("utf-8", errors="ignore")
                visible = "".join(c for c in raw_text if c.isprintable() or c in "\n\r\t ")
                lines = [l.strip() for l in visible.split("\n") if len(l.strip()) > 30]
                text = "\n".join(lines[:500])
                if len(text) < 50:
                    raise ValueError("无法提取足够文本")
                result.append({"type": "text_file", "name": uf.name, "text": text})
            except Exception:
                st.toast(f"⚠️ .doc 格式兼容性有限，建议转为 .docx 或 PDF 后上传")
    return result

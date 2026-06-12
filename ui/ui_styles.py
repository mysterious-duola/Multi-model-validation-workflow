"""CSS 样式常量 — 集中管理，避免在 ui.py 中内联大段 HTML"""
import streamlit as st

MAIN_CSS = """
<style>
/* --- 选项按钮行：固定宽度+固定间距 --- */
.st-key-option_controls [data-testid="stHorizontalBlock"] {
    gap: 8px !important;
}
/* 第1列：模型选择器 */
.st-key-option_controls [data-testid="column"]:nth-child(1) {
    flex: 0 0 230px !important;
    max-width: 230px !important;
    min-width: 230px !important;
}
/* 第2列：联网搜索 */
.st-key-option_controls [data-testid="column"]:nth-child(2) {
    flex: 0 0 160px !important;
    max-width: 160px !important;
    min-width: 160px !important;
}
/* 第3列：最终查验 */
.st-key-option_controls [data-testid="column"]:nth-child(3) {
    flex: 0 0 160px !important;
    max-width: 160px !important;
    min-width: 160px !important;
}
/* 第4列：空白占位，吸收剩余空间 */
.st-key-option_controls [data-testid="column"]:last-child {
    flex: 1 1 0 !important;
    min-width: 0 !important;
}
.st-key-option_controls [data-testid="stPopover"] button[data-testid="stPopoverButton"] {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
}
.st-key-option_controls [data-testid="stPopover"] button[data-testid="stPopoverButton"],
.st-key-force_search_btn button,
.st-key-final_check_btn button {
    height: 40px !important;
    min-height: 40px !important;
    padding: 0 14px !important;
    border-radius: 8px !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-weight: 600 !important;
}
.st-key-force_search_btn button,
.st-key-final_check_btn button {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
}
.st-key-option_controls [data-testid="stPopover"] button[data-testid="stPopoverButton"] p,
.st-key-force_search_btn button p,
.st-key-final_check_btn button p {
    line-height: 1 !important;
    white-space: nowrap !important;
}
</style>
"""

SIDEBAR_HISTORY_CSS = """<style>
/* --- 历史记录行布局 --- */
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
    align-items: center !important;
    gap: 4px !important;
    flex-wrap: nowrap !important;
}
/* 左侧列：允许缩小，不换行 */
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child {
    min-width: 0 !important;
    overflow: hidden !important;
    flex-shrink: 1 !important;
}
/* 左侧内容按钮：单行省略 */
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child button {
    display: block !important;
    text-align: left !important;
    padding-left: 8px !important;
    padding-right: 8px !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child button > div {
    display: block !important;
    text-align: left !important;
    width: 100% !important;
    max-width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    box-sizing: border-box !important;
}
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:first-child button > div > span {
    display: inline !important;
    text-align: left !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* 右侧删除列：固定宽度、右对齐 */
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child {
    flex: 0 0 36px !important;
    max-width: 36px !important;
    min-width: 36px !important;
    display: flex !important;
    justify-content: flex-end !important;
}
/* 删除按钮：圆角正方形、居中 */
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 32px !important;
    height: 32px !important;
    min-width: 32px !important;
    min-height: 32px !important;
    max-width: 32px !important;
    max-height: 32px !important;
    padding: 0 !important;
    margin: 0 !important;
    border-radius: 8px !important;
    text-align: center !important;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    flex-shrink: 0 !important;
}
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button > div,
section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:last-child button > div > span {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: auto !important;
    margin: 0 !important;
    padding: 0 !important;
    text-align: center !important;
}
/* 清空全部历史按钮 */
section[data-testid="stSidebar"] button[kind="secondary"] {
    display: block !important;
    text-align: center !important;
}
</style>"""


def inject_styles():
    """注入主界面自定义 CSS"""
    st.markdown(MAIN_CSS, unsafe_allow_html=True)

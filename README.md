# 多模型科研工作流

多 AI 模型并发回答 + 交叉验证 + 最终综合审查的科研问答工具。

## 版本记录

### v2 · 2026-06-11

- **启动脚本优化**：`启动科研工作流.bat` 自动激活 venv
- **思考默认开启**：各模型硬编码默认思考参数（GPT `reasoning.effort=high`、Claude `budget_tokens=4096`、Gemini 2.x `-1` / 3.x `8192`、DeepSeek `reasoning_effort=high`、Qwen `enable_thinking=true`）

### v1

- 多模型并发独立回答
- 交叉验证：每个模型看到其他模型答案后自我修订
- DeepSeek 最终综合审查（可选）
- PDF / Word / 图片附件支持
- 历史记录侧边栏

## 安装与启动

```bash
pip install -r requirements.txt
streamlit run ui.py
```

Windows 用户也可以直接双击 `启动科研工作流.bat`。

## 配置 API 密钥

项目根目录下的 `.env` 文件存放所有 API 密钥，**不会被上传到 Git**。

首次使用，复制模板文件：

```bash
cp .env.example .env
```

然后编辑 `.env`，填入你的密钥：

```env
# 通义千问（DashScope）
QWEN_API_KEY=sk-xxxxxxxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1/responses
QWEN_MODEL=qwen3.5-flash

# DeepSeek（最终综合审查专用）
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1/chat/completions
DEEPSEEK_MODEL=deepseek-v4-flash

# OpenAI GPT
GPT_API_KEY=sk-xxxxxxxx
GPT_BASE_URL=https://api.openai.com/v1/responses
GPT_MODEL=gpt-5.4

# Google Gemini
GEMINI_API_KEY=xxxxxxxx
GEMINI_BASE_URL=https://generativelanguage.googleapis.com
GEMINI_MODEL=gemini-2.5-flash

# Anthropic Claude
CLAUDE_API_KEY=sk-ant-xxxxxxxx
CLAUDE_BASE_URL=https://api.anthropic.com
CLAUDE_MODEL=claude-haiku-4-5-20251001
```

不需要全部填满，只填你要用的模型即可。

## 更换模型

直接修改 `.env` 中对应的 `XXX_MODEL` 字段即可切换模型，无需改代码。例如：

```env
# 切换到 GPT-4o
GPT_MODEL=gpt-4o

# 切换到 Gemini Pro
GEMINI_MODEL=gemini-2.5-pro

# 切换到 Qwen Max
QWEN_MODEL=qwen-max
```

修改后重启应用即可生效。

## 接口要求

各模型使用不同的 API 协议，`base_url` 必须匹配对应格式：

| 模型 | 调用方式 | base_url 格式 |
|------|----------|---------------|
| GPT | OpenAI Responses API | `https://xxx/v1/responses` |
| Qwen | OpenAI Responses API | `https://xxx/v1/responses` |
| DeepSeek | OpenAI Chat Completions | `https://xxx/v1/chat/completions` |
| Gemini | Google Generative AI | `https://generativelanguage.googleapis.com` |
| Claude | Anthropic Messages API | `https://xxx` (会自动拼接 `/v1/messages`) |

### 使用中转/代理

如果你使用第三方中转服务，只需修改 `base_url` 指向中转地址，保持 URL 格式不变。例如：

```env
# 使用中转的 GPT
GPT_BASE_URL=https://your-proxy.com/v1/responses

# 使用中转的 Claude
CLAUDE_BASE_URL=https://your-proxy.com
```

### 添加其他兼容模型

DeepSeek 位置使用的是标准 OpenAI Chat Completions 格式，任何兼容该协议的模型（如 GLM、Moonshot、零一万物等）都可以通过修改 `.env` 中 `DEEPSEEK_*` 相关配置来复用，但注意 DeepSeek 在流程中承担的是最终综合审查角色。

## 项目结构

```
├── app/
│   ├── config.py        # 从 .env 加载配置
│   ├── models.py        # 各模型 API 调用
│   ├── workflow.py       # 并发回答 → 交叉验证 → 综合审查
│   └── pdf_export.py    # PDF 导出
├── ui.py                # Streamlit 主界面
├── .env                 # API 密钥（不上传 Git）
├── .env.example         # 密钥模板
└── requirements.txt     # 依赖
```

# Windows + 飞书科研阅读智能体交接文档

## 1. 项目状态总览

当前项目已在 Windows 环境完成并验证以下能力：

- Windows 本地部署与一键诊断、启动、停止、日志和 smoke test 脚本。
- FastAPI 后端与 Streamlit 前端。
- GPT-5.5 Responses API 中转适配，复用统一 LLM client。
- 飞书 webhook challenge、token 校验、事件去重、后台任务和机器人回复。
- 飞书用户回复隐藏工具名、路由方式和其他内部调试字段。
- 中文科研主题自动翻译为英文 arXiv 检索词。
- 渐进式 arXiv 查询、同批去重、时间过滤和候选扩大。
- “近十年”“近五年”“2018 年以来”等时间条件解析。
- 基于 SQLite 的多轮上下文持久化。
- “要近十年的”“只要 3 篇”“第 2 篇”“接收第 2 篇”等省略式追问。
- “再来 5 篇”“一共要 10 篇，再补充 5 篇”的续搜、排重和连续编号。
- 搜索结果 `position -> paper_id` 映射，追加后仍可引用第 7、8 篇。
- 批量深入阅读：支持“对这五篇都深入阅读”、全部、前 N 篇和位置范围；串行处理且单篇失败不影响其他论文。

当前仍需继续完善：

- Cloudflare Quick Tunnel 地址重启后会变化；生产环境建议使用 Named Tunnel 和固定域名。
- 飞书生产环境应启用并完整验证签名校验、事件加密及密钥轮换。
- 多进程或多实例部署时，进程内 `RLock` 不足以实现跨进程串行，应改用数据库锁或任务队列。
- 真实飞书客户端的端到端批量 PDF 深读仍需由有权限的用户完成验收。

## 2. 当前 Windows 项目路径

唯一有效项目目录：

```text
C:\Users\lenovo\Documents\codex-work\research-reading-agent-main
```

不要使用以下旧路径：

```text
F:\D\agent\research-reading-agent-main
C:\Users\lenovo\Documents\ai 助手\research-reading-agent-main
```

中文路径曾导致 Codex、虚拟环境和启动脚本解析异常。

## 3. 启动方式

```powershell
cd "C:\Users\lenovo\Documents\codex-work\research-reading-agent-main"
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\windows\start_all.ps1
```

验证：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/health"
Start-Process "http://127.0.0.1:8501"
```

停止与查看日志：

```powershell
.\scripts\windows\stop_all.ps1
.\scripts\windows\tail_logs.ps1
```

如果 PowerShell 禁止执行脚本：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\windows\start_all.ps1"
```

脚本使用 `$PSScriptRoot` 推导项目根目录、项目 `.venv`、PID 文件及 `data\logs`，不依赖调用者当前目录。

## 4. 飞书与 cloudflared 启动方式

Quick Tunnel：

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

它会生成类似下列临时 HTTPS 地址：

```text
https://xxxx.trycloudflare.com
```

飞书事件回调填写：

```text
https://xxxx.trycloudflare.com/api/feishu/webhook
```

本地 `.env` 中同步配置 `PUBLIC_BASE_URL`。Quick Tunnel 或电脑重启后地址通常变化，需要同时更新飞书开放平台事件地址和本地配置。临时地址文件和日志不得提交 GitHub。

## 5. 飞书开放平台配置

在飞书开放平台为企业自建应用启用机器人能力，并在“事件与回调/事件配置”中填写 HTTPS webhook 地址：

```text
https://xxxx.trycloudflare.com/api/feishu/webhook
```

至少订阅 `im.message.receive_v1`。机器人进群、退群事件按业务需要选择。申请读取消息和回复消息所需权限；常见权限标识可能包括 `im:message`、`im:message.p2p_msg:readonly`，具体名称和菜单位置必须以当前飞书控制台显示为准。修改权限或事件后，需要创建并发布应用版本，再将机器人加入测试群或允许私聊。

## 6. 环境变量说明

仅在本地 `.env` 配置真实值：

```env
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
OPENAI_MODEL=gpt-5.5

FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_VERIFICATION_TOKEN=...
FEISHU_ENCRYPT_KEY=
FEISHU_ENABLE_SIGNATURE_CHECK=false
PUBLIC_BASE_URL=...
```

`.env` 绝不能提交 GitHub；`.env.example` 只能保存占位符。日志中不得输出 App Secret、Verification Token、tenant access token 或完整消息正文。

## 7. 主要新增能力说明

### 7.1 GPT-5.5 Responses API 适配

LLM 调用通过共享 client 走 Responses API 兼容接口，不再由业务模块各自拼接 `/chat/completions`。模型名、base URL 和认证信息均来自本地配置。

### 7.2 飞书 webhook

```text
Feishu webhook
-> routes_feishu
-> FeishuService
-> ConversationFollowupService
-> AgentService / ToolRegistry
-> PaperService
-> 飞书回复
```

webhook 快速返回 200，耗时 Agent 查询和论文处理由 `BackgroundTasks` 执行。日志记录事件、token 校验、去重、Agent 和回复阶段，但不记录消息正文与密钥。

### 7.3 中文自动翻译

```text
中文查询 -> GPT-5.5 翻译为英文检索词 -> arXiv 搜索 -> 中文初筛回复
```

若 LLM 翻译不可用，服务保留安全降级路径。

### 7.4 渐进式 arXiv 检索

检索按 strict、relaxed、synonym expansion、loose fallback 分层执行。每层先获取扩大后的候选集，再进行 arXiv ID/URL 去重、会话排除和时间过滤，最后截取用户需要的数量。`http/https` 与 `abs/pdf` URL 变体会归一化处理。

### 7.5 多轮上下文

SQLite 表：

```text
conversation_turns
conversation_task_state
```

飞书 `session_id` 规则：

```text
私聊：feishu:p2p:{chat_id}
群聊：feishu:group:{chat_id}:{open_id}
群聊线程：feishu:group:{chat_id}:{root_id_or_parent_id}:{open_id}
```

支持：

```text
要近十年的
只要3篇
第2篇
接收第2篇
对第2篇做深入阅读
再来5篇
一共要10篇，再补充5篇
对这五篇都进行深入阅读
对第6到第10篇做深入阅读
重新开始
```

### 7.6 续搜与排重

- “再来 5 篇”继承上次 query、时间范围和数量条件。
- 当前会话已展示的 URL、`paper_id` 和 arXiv ID 会作为内部排除集合。
- 第二批用户可见编号从 6 开始。
- `result_refs` 追加保存，后续“第 7 篇”会解析到真实 `paper_id`。
- 主题或时间条件替换属于重搜，会替换结果引用而非追加。

### 7.7 批量深入阅读

确定性规则优先识别“全部”“这五篇”“前 5 篇”和“第 6 到第 10 篇”。内部 `batch_ingest_papers` 串行复用单篇 `ingest_paper`；单篇失败会记录并继续。`read_paper`/`read_papers` 别名会在 Agent 边界映射，不会暴露给用户。批量完成后保留搜索 `result_refs`，并把最后成功处理的论文设为当前焦点。

## 8. 常用测试命令

```powershell
.\.venv\Scripts\python.exe -m compileall -q app frontend tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q tests\test_feishu_webhook.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_conversation_followup_service.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_progressive_arxiv_search.py
```

最近一次完整测试：

```text
322 passed, 1 warning in 15.38s
```

唯一警告为现有 Starlette/httpx 测试客户端弃用提示。

## 9. 真实飞书验收脚本

建议依次发送：

```text
重新开始
帮我搜索5篇VLF传播时延相关论文
要近十年的
只要3篇
再来5篇
第7篇
接收第8篇
对第2篇做深入阅读
对这五篇都进行深入阅读
```

预期：不显示工具名、路由方式或 `session_id`；省略式追问继承主题；续搜不重复上一批；位置引用映射到真实论文；批量深入阅读逐篇显示完成或失败状态。

## 10. 已知问题与下一步

1. Quick Tunnel 不是固定地址，生产环境改用 Named Tunnel。
2. 飞书生产安全需要启用并验证签名校验、事件加密和密钥轮换。
3. 数据库历史中可能已有旧重复 URL，不建议未经备份直接删除。
4. 多进程部署需以数据库锁或队列替代进程内 `RLock`。
5. 需要有权限的用户完成真实飞书批量深入阅读验收，并观察 PDF 下载失败时的降级表现。

批量深入阅读的 `read_papers` 问题已在当前版本解决，不再作为未完成项。

## 11. GitHub 提交流程

本次发布信息：

```text
目标仓库：https://github.com/mxz-dddd/research-reading-agent
分支：windows-feishu-context-handoff
提交信息：Add Windows Feishu deployment and conversation context handoff
验证：322 passed, 1 warning
```

提交前已确认 `.env`、虚拟环境、数据库、PDF、下载论文、运行日志、调试备份和临时公网地址均被忽略。发布分支基于远端 `main`，draft PR 与最终 commit SHA 以 GitHub 页面记录为准。

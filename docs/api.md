# API 与实际字段来源

## Webhook

`POST /webhook`、`POST /webhook/portkey`、`POST /webhook/panw` 是相同契约的别名。
路径名 `/panw` 不表示实现了 PANW 的所有 API。要求：

```http
Authorization: Bearer <WEBHOOK_TOKEN>
Content-Type: application/json
```

支持的 `eventType`：`beforeRequestHook` 与 `afterRequestHook`。省略时按 before 处理。
示例见 `examples/before-request.json` 与 `examples/after-request.json`，内容均为合成测试数据。

### 输入提取与扫描范围

优先解析 `request.json`，然后解析文本型 `messages[].content`、`prompt`、`input`、
`text` 或 `content`。文本内容块可以使用 `{ "type":"text", "text":"..." }`。
图片、音频、工具专用非文本消息和不支持的结构拒绝处理，不静默当成安全内容。

before 扫描输入中的**全部消息文本**。当前实现将角色内容拼接为单个 user 文本交给
Qwen 分类；不会声称这是对业务模型完整角色上下文的等价推理。日志另行保留原有角色。
after 扫描 `response.json.choices[].message.content` 等响应文本，并使用请求文本作为
分类上下文。用于日志的上下文会单独经 Presidio 遮盖。

PII 优先：检测到 PII 即阻断并跳过 Qwen。主界面的摘要取最后一个 user，**摘要不代表
扫描范围**；历史 assistant 示例号码也可能造成新一轮阻断。

### 响应

```json
{
  "verdict": false,
  "data": {
    "action": "deny",
    "pii": [{"entity_type":"EMAIL_ADDRESS","start":3,"end":19,"score":0.85}],
    "safety": {"label":"Skipped","categories":"PII"},
    "eventType": "beforeRequestHook"
  }
}
```

PII `start` / `end` 是被扫描文本中的 Unicode 字符偏移，end 不包含在内；不是 UTF-8
字节偏移，也不一定是本轮摘要中的偏移。Presidio 的数值 score 与 Qwen 无关。
Qwen 返回 Safe / Unsafe / Controversial 标签和分类字符串，没有数值置信度。

HTTP 状态含义：

- `200`：成功执行检查，必须继续读取布尔 `verdict`。
- `401`：Webhook Token 无效。
- `413`：请求体超过 128 KiB 或文本超过 12000 字符。
- `422`：空输入、错误事件类型、不支持的文本结构等。
- `503`：检测依赖失败、模型忙碌/超时、上下文超限或无法解析判定；网关应按失败阻断。

模型内部 `/moderate` 的上下文上限为 4096 tokens，生成上限为 96 tokens；WebHook
不会静默截断输入。内部服务不提供跨主机访问契约，不应直接暴露。

## 健康检查

`GET /health` 不需要 Token，验证两个依赖是否可用；成功返回 status 与应用 version。
它不运行一次实际推理，不代表模型分类正确，也不保证日志磁盘还有足够空间。

## 日志鉴权

日志的 Token 为独立的 `LOGS_TOKEN`：

- `POST /api/logs/login`：JSON `{ "token":"<LOGS_TOKEN>" }`，成功设置 8 小时
  HttpOnly / SameSite=Strict Cookie。HTTP 内网部署不设置 Secure；TLS 终止策略由部署者管理。
- `POST /api/logs/logout`：清除当前浏览器 Cookie。
- 日志读取也支持 `Authorization: Bearer <LOGS_TOKEN>`，不能使用 Webhook Token。

会话 Cookie 使用 Token 派生签名。轮换 LOGS_TOKEN 并重建 webhook 后旧 Cookie 失效。
当前没有用户/角色系统、个人审计权限或公开互联网登录保护，应限制在可信内网。

## 日志查询

`GET /api/logs` 返回 items、total、counts、pii_requests、updated_at 与分页信息。

- `limit`：25 / 50 / 100 / 250 / 500；默认 100。
- `offset`：0 到 10000。
- `outcome`：all / allowed / blocked / error / rejected。
- `q`：最长 200 字符，搜索遮盖后的摘要、Trace ID、模型与分类；% 与 _ 按字面匹配。

`GET /api/logs/{id}` 返回 `scan` 以及同一 Trace ID 的最近最多 20 条 `related`。
超过保留期或不存在的记录为 404。列表不返回完整快照，以控制负载。

### 日志 payload v3

- `content`：扫描文本的遮盖日志副本。
- `guard_input`：实际本地 Qwen 请求的遮盖副本，以及是否执行；不等于业务 LLM 的输入。
- `timing`：Presidio、Qwen HTTP、模型推理、快照遮盖、Webhook 总耗时。部分计时重叠，
  不能简单相加当作端到端耗时。
- `observation.snapshot`：网关发给 Webhook 的结构化 JSON 副本；凭据字段移除、检出 PII 遮盖。
- `observation.messages`：角色、顺序、文本、内容类型与工具调用数量。
- `observation.latest_user`：最后一个 user 消息；不会删除相邻重复消息。
- `observation.parameters`、`metadata`、request/response 字段列表：网关实际上报的参数。
- `pii_sources`：before 阶段 PII 所在消息角色、序号、局部偏移与是否属于最后一个 user。
- `usage`：仅保存网关响应上报的非负整数用量，不估算。
- `client_original_confirmed` / `llm_received_confirmed` / `client_received_confirmed`：
  当前均为 false，因为该 Webhook 没有这些阶段的直接观测。

快照限额：字符串总预算 64000 字符、单字符串 14000 字符、单层最多 128 项、最多 14 层。
超出限额标记 `snapshot_truncated`。日志增强失败会写 capture_error，不回退保存原文，也不
改变已经作出的安全判定。识别器未发现的 PII 仍可能进入日志。

旧日志可读取，但无法补造此前未保存的角色、快照或分项耗时。


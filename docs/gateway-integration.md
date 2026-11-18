# PANW AI Gateway / SCM 接入

本项目提供 Portkey 风格 Webhook 契约。PANW AI Gateway 的 Guardrail 和路由策略
由 SCM 保存并下发；仅启动本项目不会自动改变任何网关策略。

## 1. 先验证访问路径

假设检测主机的私网地址是 `10.20.0.10`，网关位于另一台内网主机。

1. 在检测主机 `.env` 中设置 `WEBHOOK_BIND_HOST=10.20.0.10`，重新创建 webhook 服务。
2. 从网关主机访问 `http://10.20.0.10:18080/health`。
3. 如果网关在容器中，也从那个容器验证访问；主机可通不代表容器一定可通。
4. 取得检测主机 `.env` 中的 `WEBHOOK_TOKEN`。日志登录的 `LOGS_TOKEN` 不能用于这里。

不要将本项目回环地址 `127.0.0.1` 填到另一台网关上：它会指向网关自己。
对于跨主机 HTTP，Token 会经过内网传输；按部署环境配置受信任的 TLS 反向代理，
不要为了测试关闭证书验证。本仓库不自动提供公网入口。

## 2. SCM 的 Webhook 检查

按当前产品版本的 UI 添加 Webhook 检查，填写：

- **Webhook URL**：`http://10.20.0.10:18080/webhook/panw`。
- **Headers**：下面的 JSON，其中占位符替换成实际 Webhook Token。
- **Timeout**：`95000` 毫秒；CPU 推理和排队可能超过默认的 3000 毫秒。
- **Fail if the webhook returns a non-200 status or times out**：开启。
- **Forward Headers**：可显式填写 `x-portkey-trace-id`，不要转发认证 Header 或使用通配符。
- **Execute on Proxy Requests**：标准 Chat Completions 先关闭；原始代理请求需在确认其
  文本格式能被此 Webhook 解析后单独启用和验证。本项目不支持任意原始 HTTP 请求体。

```json
{
  "Authorization": "Bearer <WEBHOOK_TOKEN>",
  "Content-Type": "application/json"
}
```

Guardrail 的附加设置：

- **Deny on Failure**：开启。
- **Run Asynchronously**：关闭；必须等待结果才能阻断。
- **Soft deny**：关闭；防止客户端将 HTTP 200 的错误消息当成正常模型输出。
- **Execute guardrails sequentially**：只有一个检查时无需开启；多个检查按实际依赖配置。
- 自定义错误提示可使用“请求因包含敏感信息或违反内容安全策略而被阻断。”

把 Guardrail 关联到路由的输入钩子；需要输出检查时，也配置输出钩子。
在 SCM 保存、提交并下发。测试时确认实际调用的路由、配置版本和模型均匹配。

## 3. 内网 URL 被 SSRF 策略拒绝

错误示例：`Webhook error: webhookURL rejected by SSRF policy`。
这表示网关**在发送 HTTP 请求前**拒绝了 URL；检测服务不会产生对应的 Webhook 日志。

已验证的 PANW AI Gateway Enterprise 2.33.1 部署使用 `TRUSTED_CUSTOM_HOSTS`
控制自定义信任目标。需要网关管理员按现有变更流程，仅追加检测主机的准确地址：

```yaml
environment:
  TRUSTED_CUSTOM_HOSTS: "existing.example.internal,10.20.0.10"
```

上面只是配置片段，不是完整网关部署文件。保留所有原有条目，先备份，再验证配置，
并在获准的维护时段重新创建网关容器。普通 `restart` 不会更新容器环境变量。

不要关闭 SSRF 防护、放行整个内网或添加 `*`。宿主机 `curl` 可达与通过网关的
SSRF 校验是两件事，均需验证。其他产品版本以相应官方文档为准。

## 4. Portkey 配置片段

合并 `examples/portkey-config.json` 到已有配置，保留原路由、Provider、凭据和预算设置。
它只声明 before/after hooks，不包含可直接调用上游模型的完整路由。

关键字段：`default.webhook`、`deny:true`、`async:false`、`failOnError:true`。
`verdict:false` 即使伴随 HTTP 200 也应阻断；503、超时和鉴权错误则由 fail-on-error 阻断。

## 5. Trace ID 与业务元数据

建议请求携带唯一的 `x-portkey-trace-id`。本项目按以下来源读取 Trace ID：

1. HTTP Header `x-portkey-trace-id`。
2. Webhook 顶层 `traceId`。
3. `metadata.trace_id`。

同一 Trace ID 可以关联输入和输出阶段。不要用同一个会话 ID 替代每次调用的 Trace ID；
标题生成（如 `metadata.feature=title`）也不应与聊天请求（`feature=chat`）混配。
没有 Trace ID 时页面会明确说明无法关联，不会按时间猜测。

同一 Trace ID 被重用于多次重试时，页面展示选中阶段和最近的另一阶段；这不是严格的
分布式调用树，也不是送达证明。

## 6. 流式与非流式

`stream:true` 不妨碍 before hook 在业务模型生成前执行。输出 hook 是否触发、收到的
响应形态和缓冲方式取决于网关版本及配置。即使触发 after hook，先前流出的内容也
可能已经送达客户端。需要输出严格拦截时，使用 `stream:false` 或明确配置完整响应缓冲。

本仓库不部署 Qwen3Guard-Stream，不提供 token/chunk 级实时拦截协议。

## 7. 验收顺序

先在一个新的短会话发送普通问候，确认日志出现 `Safe` / allowed；然后用测试手机号
确认 `verdict:false`；最后验证依赖故障或错误 Token 在网关侧不会放行。不要用真实
个人信息测试，也不要通过关闭 Deny/Fail-on-error 来“修复”连通性。

网关失败而 `/logs` 无新记录时，优先检查 SCM 是否下发、路由是否引用、URL、端口、
容器连通性、SSRF 信任目标和请求 Header。已有记录但被阻断时，检查分类、PII 来源、
扫描历史和真实状态码。主页面只显示本轮摘要，实际检测仍覆盖传入的整段对话文本。

参考：[Portkey Webhook 实现](https://github.com/Portkey-AI/gateway/blob/main/plugins/default/webhook.ts)、
[PANW Guardrail 创建说明](https://origin-docs.paloaltonetworks.com/prisma-airs/ai-gateway/ai-gateway-guardrails/create-a-guardrail)。


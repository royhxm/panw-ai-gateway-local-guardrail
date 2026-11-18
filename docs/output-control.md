# PANW AI Gateway：输出控制与日志关联（v0.2.0）

## 固定的业务架构

**Aurora → PANW AI Gateway → 业务模型。**

由 AI Gateway 调用本服务 `/webhook/panw` 进行输入/输出检查。
本项目不提供前置业务代理，不要求 Aurora 改为先访问检测服务。
SCM 管理路由与安全策略；本次版本不更改现有网关网络安全策略。

## 输入和输出控制

原有 Webhook 默认行为：PII / Unsafe / Controversial 阻断，Safe 放行。
它只给网关返回判定，不修改业务请求/响应，也不缓存业务 SSE。
SCM 必须同步执行检查，启用 Deny on Failure，并将 Webhook 非 200 / 超时按失败处理。
输入和输出分别挂在 before_request_hooks / after_request_hooks。

`afterRequestHook` 的调用成功不代表网关一定阻断，必须以客户端收到的结果为验收依据。
HTTP 200 + verdict:false 是内容拒绝；HTTP 422 是解析/格式失败，HTTP 503 是检查依赖不可用。
日志明确区分这些情况。

## 流式输出的边界

当前自定义 Webhook 不能撤回已经送达客户端的 token。
完整输出检查也不能被当成逐 token 的实时审核。
严格控制正文释放，应先以 `stream:false` 验证输出阻断。
若要在保持 Aurora 首先访问 AI Gateway 的前提下保留流式兼容，需要 AI Gateway 本身支持
完整缓存后检查、放行；不能仅靠本 Webhook 实现，也不能假设开启 Deny 即具备缓存能力。
应在已部署版本验证该能力，或采用 PANW 官方支持的网关侧机制。
本版本未增加任何改变上述调用路径的代理。

## PII 策略

默认命中即阻断；日志中的占位符只保护日志，不代表业务正文被替换。
中文连续手机号、校验有效的身份证号、邮箱是当前支持重点；不是完整人名/地址 NER。
若需要“脱敏后继续”，必须由 AI Gateway 的受支持响应/请求变换机制实际改写正文，
并验证 LLM 收到及客户端返回的内容均已替换。普通自定义 Webhook 返回任意 `action:redact`
不能直接被视为修改成功。本版不宣称已实现业务流量脱敏。

## Trace ID 与阶段关联

网关 `x-portkey-trace-id`、业务 `metadata.trace_id`、`session_id` 分开显示。
关联优先使用网关请求头，其次 body.traceId，再其次应用 metadata.trace_id。
SCM Forward Headers 可填 `x-portkey-trace-id`，不要在固定 Headers 中填一个常量。
同一个会话可产生多个模型调用；会话 ID 不用于自动配对。
同 Trace 多个相反阶段记录时，界面明确提示歧义，不猜测重试归属。
可以点击同 Trace 记录查看各个候选；应用 Trace 和网关 Trace 都可以搜索。
旧数据没有请求头来源记录时，不能确证主 Trace 的来源，也不能补回未采集的内容。

## OUTPUT 422 排查

现在空/无正文 JSON 会尝试外层 text；畸形 messages/choices、多模态等仍拒绝。
解析失败会保存具体错误与脱敏快照；脱敏依赖失败时只保存失败标记，不回退保存原文。
空输出默认拒绝，避免把“没有可扫描内容”误标为安全。
历史日志的原文无法恢复。

## 运行指标和验收

登录日志页后可查看近 24 小时阶段检查数、内容阻断、调用异常、P50/P95 延迟。
`GET /api/metrics` 使用日志 Token 或登录 cookie 鉴权；指标不含正文。
一次业务调用通常含两次阶段检查，此数值不是用户请求数。
模型现有队列最多容纳 4 个推理调用，单次等待锁最多 60 秒，超限失败关闭。

建议上线验证：正常放行、输入 PII、输出 PII、恶意输入、不安全输出、检查依赖不可用、
重复 Trace、多次会话调用。验收还必须检查网关最终给客户端的结果。
运行 `python -m pytest -q` 验证确定性行为；`scripts/smoke_test.py` 验证真实模型/PII 服务。
额外运行 `WEBHOOK_TOKEN` 环境变量配置后的 `python scripts/evaluate_safety.py --base-url <private-url>`，
可评估 examples/safety-cases.json 中的中文、提示注入、数字误报样本。
工具只输出案例 ID、判定和延迟；误报、漏报和调用故障分开识别。
模型安全效果应在你自己的中文样本集上持续评估；小样本通过不是全场景保证。

## 本次小样本诊断（2026-11-18）

实际 CPU 模型运行的 8 个诊断样本中，6 个符合预期：正常中文和防御性问题放行，
直接提示注入、角色伪造、中文手机号和邮箱阻断。
另有 2 个已知问题：普通数字 `123123` 被误判 Unsafe；网页注释中的间接注入被判为 Safe。
这些问题没有用特殊放行或虚构分数掩盖，应作为后续模型/规则评估重点。
此结果不是准确率基准，也不代表实际业务的安全保证。

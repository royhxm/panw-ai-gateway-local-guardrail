# Changelog

版本遵循 Semantic Versioning。这里记录项目能力，不包含私有部署的地址、Token、日志或业务数据。

## [0.2.1] - 2026-11-18

- Allow explicitly successful, structurally valid Chat Completion responses with no text; mark output scanning skipped, never Safe.
- Preserve input checks, all non-empty output checks, and rejection of errors, malformed responses and unsupported message fields.
- Show no-text skip reason in list/detail views and preserve usage, Trace IDs and masked snapshots.

## [0.2.0] - 2026-11-18

- Separate gateway/application Trace IDs, preserve session identity, avoid automatic pairing when retries create multiple candidates.
- Capture masked validation failures with concrete reasons; fall back from empty JSON to text safely.
- Add authenticated 24-hour scan/error/latency metrics and dashboard summary.
- Add regression coverage for output parsing, trace ambiguity, error masking and metrics.

## [0.1.0] - 2026-11-18

首个公开版本：**PANW AI Gateway Local Guardrail**。

### Added

- Linux Docker Compose 三服务部署：Qwen3Guard-Gen-0.6B、Microsoft Presidio、FastAPI Webhook。
- PyTorch CPU wheel、动态 INT8 Linear 量化、固定模型 revision 与权重 SHA-256 验证。
- 中文手机号、日期/校验码有效的 18 位身份证和邮箱识别。
- Portkey 风格 before/after Webhook，布尔 verdict、PII 优先阻断、Safe-only 放行。
- PANW AI Gateway / SCM 配置指南，包含 deny、fail-on-error、超时、Trace ID 和 SSRF 信任目标。
- 独立 Webhook / 日志 Token、8 小时日志会话、SQLite 持久化、30 天 / 10000 条保留策略。
- 角色化消息、相邻重复提示、历史 PII 归因、本轮摘要、网关原始快照日志副本。
- 六阶段来源面板，明确区分客户端原始请求、网关检查快照、业务 LLM 接收与客户端送达证据。
- Qwen 检测输入与业务 LLM 请求分开呈现，缺失的上游耗时、usage 和阶段不编造。
- 可配置地址/端口、默认回环绑定、独立随机凭据生成、安装与模型下载脚本。
- API、运维、升级、流式限制和已知模型误判/漏检文档。
- 自动化回归测试与 GitHub Actions CI；运行中完整栈 smoke test。

### Changed for public distribution

- 将原来的部署专用常量改为环境配置，去除所有实际服务器 IP、用户凭据和真实请求。
- 日志默认使用独立随机 Token；不复用 Linux 登录密码。
- 仅发布应用源代码和合成示例，不发布权重、网关镜像、运行数据库或真实截图。

### Known limitations

- 不是 Qwen3Guard-Stream；流式输入可检查，不能保证流式输出先审后发。
- 0.6B 生成式分类存在误报、漏报和间接提示注入漏检，未提供安全覆盖率保证。
- 不是完整中文 NER/DLP，也不支持所有多模态、工具和原始代理请求形式。
- 当前为单机 host 网络、单模型推理、四个执行/等待名额；没有多租户审计权限系统。
- 未识别的敏感内容仍可能进入明文日志；只有检出的 PII 会被遮盖。

[0.1.0]: https://github.com/royhxm/panw-ai-gateway-local-guardrail/releases/tag/v0.1.0


[0.2.0]: https://github.com/royhxm/panw-ai-gateway-local-guardrail/releases/tag/v0.2.0

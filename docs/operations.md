# 安装、运维、备份与升级

## 配置和目录

`.env` 由初始化脚本生成，已有时保留。修改后要重新创建受影响的容器，单纯 restart
不会更新环境变量。

- WEBHOOK_BIND_HOST：默认 127.0.0.1，可改为本机实际拥有的私网地址。
- WEBHOOK_PORT：默认 18080。
- QWEN_PORT / PRESIDIO_PORT：默认 18081 / 18082；均仅监听回环。
- WEBHOOK_TOKEN / LOGS_TOKEN：至少 32 字符的两个独立随机值。
- MODEL_CACHE_DIR：默认 `./model-cache`，容器只读挂载；模型位于其中的 `model/`。
- LOGS_DATA_DIR：默认 `./logs-data`，容器 UID 10001 可写。
- GUARDRAIL_IMAGE：发布镜像的本地构建标签，初始为 local-guardrail:0.1.0。
- CPU_THREADS：默认 4，按主机 CPU 和其他工作负载配置。

变更自定义数据目录后，初始化脚本不会自动接管任意目录。请手动创建正确路径并验证
权限、归属、备份和可用空间，不要对不确定的路径执行递归 chown。

## 常用操作

```bash
docker compose ps
docker compose logs --tail 100 webhook
docker compose logs --tail 100 qwen3guard
docker stats --no-stream

# 重建代码 / 修改环境配置后应用
docker compose build
docker compose up -d --wait --wait-timeout 180

# 停止，保留模型和日志
docker compose stop
```

容器配置为 `restart: unless-stopped`。Docker 守护进程必须在开机时启动。被显式 stop
的容器不会自动恢复，需执行 up/start。所有服务使用 host 网络，先检查配置端口是否
被占用，尤其是另一个项目也部署了相同内部端口时。

## 常见故障

**模型找不到或无法加载**：核对 MODEL_CACHE_DIR 与 `model/` 内文件；执行
`python3 scripts/download_model.py --verify-only`。模型运行时为离线模式，不会自动下载。
校验失败的已有权重不会被下载脚本覆盖；使用独立的新缓存目录排查。

**Permission denied / SQLite unable to open**：核对容器 UID 10001 是否能访问完整目录链。
修正项目专用的 logs-data / model-cache 归属，不要 chmod 777 或修改系统根目录权限。

**健康但请求 503**：健康检查只验证依赖健康端点。实际请求可能超出上下文、模型排队
超时、无法解析标签或耗尽内存。查看 Qwen 和 Webhook 日志以及内存/OOM 状态。

**主机可达，网关仍 SSRF 拒绝**：这是网关 URL 安全策略，见接入文档；不应关闭安全开关。

**一条普通消息也被阻断**：检查完整历史、PII 角色归因与模型误判，开新会话对照。UI
只展示最后一个 user 摘要，不会缩小实际扫描范围。不要因误判直接关闭所有阻断。

**日志为空**：确认请求是否到达；SCM 路由未关联、规则未下发、错误 URL、SSRF、Token
和网络失败都可能导致不同表现。401 和解析失败可有拒绝记录；网关发出前拦截不会有记录。

**只有输入记录**：核对输出 Guardrail 是否关联、是否使用流式，以及是否提供同一 Trace ID。
标题生成和聊天是不同业务调用，不要按相同模型名或会话 ID 拼接成一次请求。

## 备份

源代码与模型下载元数据可由 Git / 本仓库重建，日志和配置需要私下备份。

```bash
# 创建 SQLite 一致快照，避免直接复制活动 WAL 文件造成不完整备份
docker compose exec -T webhook python - <<'PY'
import datetime,sqlite3
path='/data/backup-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.sqlite3'
with sqlite3.connect('/data/scans.sqlite3') as source,sqlite3.connect(path) as target:
    source.backup(target)
print(path)
PY
```

将快照、`.env` 及必要配置保存到受控备份位置。数据库含非公开内容，绝不能提交到 GitHub。
快照也占用磁盘；项目不会自动清理手动创建的备份。恢复前先停 webhook，保留当前副本，
由管理员确认目标文件和权限后恢复；不要对活动 WAL 数据库直接覆盖文件。

## Token 轮换

在自己的终端用 `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` 生成新值，
编辑 `.env`。替换 WEBHOOK_TOKEN 后，同步更新 SCM 中的 Webhook Header 并下发；
替换 LOGS_TOKEN 后，所有旧日志会话失效。两个 Token 应分别管理。

```bash
docker compose up -d --no-deps --wait webhook
```

不要将 Token 写入公开 Issue、命令截图、Release、shell 调试日志或仓库示例。

## 升级与回退

先阅读 CHANGELOG，私下备份 .env、数据快照和当前提交。选择明确的 tag：

```bash
git fetch --tags origin
# 示例占位符，不要直接执行不存在的版本
git checkout <target-tag>
# 比较 .env.example，保留自己的 Token，按目标版本更新 GUARDRAIL_IMAGE
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 180
python3 scripts/smoke_test.py
```

当前数据库对 payload 列等使用增量兼容处理，但未来版本可能增加迁移要求；不能假设
任意新旧版本之间都能原地回退。停止写入、恢复一致快照和原版本镜像应在维护计划内执行。

## 开发隔离

测试第二套完整栈时，使用不同的 Compose project、独立日志目录和三个不同端口。
host 网络不因 project 名自动隔离端口。模型缓存可以只读共享，日志库不得共享写入。


"use strict";
const $ = (id) => document.getElementById(id);
let items = [],
  offset = 0,
  total = 0,
  pending = false,
  queued = false;
const outcomes = {
  allowed: "已放行",
  blocked: "已阻断",
  error: "检测异常",
  rejected: "请求拒绝",
};
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
function showLogin(message = "") {
  $("login").classList.remove("hidden");
  $("dashboard").classList.add("hidden");
  $("logout").classList.add("hidden");
  $("connection").textContent = "需要登录";
  $("login-error").textContent = message;
}
function showDashboard() {
  $("login").classList.add("hidden");
  $("dashboard").classList.remove("hidden");
  $("logout").classList.remove("hidden");
  $("connection").textContent = "日志已连接";
}
function dateParts(value) {
  const d = new Date(value),
    tz = $("timezone").value;
  return [
    new Intl.DateTimeFormat("sv-SE", {
      timeZone: tz,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(d),
    new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(d),
  ];
}
function render() {
  const rows = $("rows");
  rows.replaceChildren();
  for (const item of items) {
    const row = el("tr");
    const time = el("td", "date");
    const [day, clock] = dateParts(item.timestamp);
    time.append(el("span", "", day), el("small", "", clock));
    row.append(time);
    const result = el("td");
    result.append(
      el(
        "span",
        "badge " + item.outcome,
        outcomes[item.outcome] || item.outcome,
      ),
      el("span", "http", "HTTP " + item.http_status),
    );
    row.append(result);
    const safety = el("td");
    safety.append(
      el(
        "span",
        "label",
        item.categories === "NoText"
          ? "无正文 · 扫描跳过"
          : item.safety_label === "Skipped"
            ? "模型跳过 · PII 优先"
            : item.safety_label || "未完成检测",
      ),
    );
    for (const cat of (item.categories || "").split(/,\s*/).filter(Boolean))
      safety.append(el("span", "tag", cat));
    row.append(safety);
    const pii = el("td");
    const counts = {};
    for (const hit of item.pii)
      counts[hit.entity_type] = (counts[hit.entity_type] || 0) + 1;
    for (const [key, n] of Object.entries(counts))
      pii.append(el("span", "tag", key + " ×" + n));
    if (!item.pii.length) pii.append(el("span", "muted", "—"));
    row.append(pii);
    const content = el("td");
    content.append(
      el(
        "span",
        "event",
        item.event_type === "afterRequestHook" ? "OUTPUT" : "INPUT",
      ),
      el("span", "summary", item.summary),
    );
    if (item.message_count !== null && item.message_count !== undefined) {
      content.append(
        el(
          "span",
          "message-info",
          item.message_count +
            " 条对话消息" +
            (item.duplicate_count
              ? " · " + item.duplicate_count + " 组重复"
              : "") +
            (item.stream === 1 ? " · 流式" : "") +
            (item.feature ? " · " + item.feature : ""),
        ),
      );
    } else
      content.append(el("span", "message-info", "历史合并摘要 · 角色未采集"));
    if (item.trace_id)
      content.append(el("span", "trace", "关联 Trace: " + item.trace_id));
    if (
      item.application_trace_id &&
      item.application_trace_id !== item.trace_id
    )
      content.append(
        el("span", "trace", "应用 Trace: " + item.application_trace_id),
      );
    row.append(content);
    row.append(
      el("td", "model", item.model || "—"),
      el("td", "latency right", item.latency_ms + " ms"),
    );
    const action = el("td");
    const button = el("button", "detail-button", "↗");
    button.setAttribute("aria-label", "查看扫描 " + item.id + " 的详情");
    button.onclick = (event) => {
      event.stopPropagation();
      details(item);
    };
    action.append(button);
    row.append(action);
    row.onclick = () => details(item);
    rows.append(row);
  }
  $("empty").classList.toggle("hidden", items.length > 0);
  $("time-heading").textContent =
    "时间 (" + ($("timezone").value === "UTC" ? "UTC" : "SGT") + ")";
  const limit = Number($("limit").value);
  $("range").textContent = total
    ? `${offset + 1}–${offset + items.length} / ${total}`
    : "0 条";
  $("page").textContent =
    `${Math.floor(offset / limit) + 1} / ${Math.max(1, Math.ceil(total / limit))}`;
  $("prev").disabled = offset === 0;
  $("next").disabled = offset + limit >= total;
}
function detailRow(parent, label, value) {
  const row = el("div", "kv-row");
  row.append(
    el("span", "kv-label", label),
    el("span", "kv-value", value ?? "未提供"),
  );
  parent.append(row);
}
function section(parent, title) {
  const block = el("section", "detail-section");
  block.append(el("h3", "detail-section-title", title));
  parent.append(block);
  return block;
}
function guardCard(parent, record, phase) {
  const block = section(
      parent,
      phase === "input"
        ? "GUARDRAIL · INPUT（LLM 之前）"
        : "GUARDRAIL · OUTPUT（LLM 之后）",
    ),
    card = el("div", "detail-card");
  block.append(card);
  if (!record) {
    card.append(
      el(
        "p",
        "muted",
        "未收到此阶段记录。通过相同 Trace ID 可关联输入和输出。",
      ),
    );
    return;
  }
  const p = record.payload || {},
    t = p.timing || {};
  detailRow(
    card,
    "Guardrail",
    (p.guardrail_id || "未提供 ID") + " · " + (p.check || "default.webhook"),
  );
  const verdict = el("div", "kv-row");
  verdict.append(
    el("span", "kv-label", "Verdict"),
    el("span", "badge " + record.outcome, outcomes[record.outcome]),
  );
  card.append(verdict);
  detailRow(
    card,
    "Qwen3Guard",
    (record.categories === "NoText"
      ? "未执行 · 上游成功且无正文"
      : record.safety_label === "Skipped"
        ? "未执行 · PII 优先阻断"
        : (record.safety_label || "未完成") +
          " / " +
          (record.categories || "未提供分类")) +
      (t.qwen_request_ms !== undefined
        ? " · " + t.qwen_request_ms + " ms"
        : ""),
  );
  const counts = {};
  for (const hit of record.pii || [])
    counts[hit.entity_type] = (counts[hit.entity_type] || 0) + 1;
  detailRow(
    card,
    "Presidio PII",
    (record.categories === "NoText"
      ? "未执行（无正文）"
      : Object.entries(counts)
          .map(([k, n]) => k + " ×" + n)
          .join(" · ") || "未检出") +
      (t.presidio_ms !== undefined ? " · " + t.presidio_ms + " ms" : ""),
  );
  detailRow(
    card,
    "PII 处理",
    record.pii?.length
      ? "命中即阻断；仅日志副本遮盖检出的 PII"
      : "未触发 PII 阻断",
  );
  detailRow(card, "Check time", record.latency_ms + " ms");
  detailRow(card, "Webhook 状态", "HTTP " + record.http_status);
  if (record.detail) detailRow(card, "异常原因", record.detail);
  if (!p.version)
    card.append(
      el("p", "legacy-note", "历史记录：当时未采集分项耗时和完整内容。"),
    );
}
function contentPair(
  parent,
  title,
  leftTitle,
  leftText,
  rightTitle,
  rightText,
) {
  const block = section(parent, title),
    grid = el("div", "content-grid");
  block.append(grid);
  for (const [heading, text] of [
    [leftTitle, leftText],
    [rightTitle, rightText],
  ]) {
    const card = el("div", "detail-card content-card");
    card.append(el("h4", "", heading), el("pre", "", text || "未提供"));
    grid.append(card);
  }
}
function sourceCard(
  parent,
  number,
  title,
  status,
  source,
  note,
  observed = false,
) {
  const card = el(
    "article",
    "source-card " + (observed ? "observed" : "unobserved"),
  );
  card.append(
    el("span", "source-number", String(number).padStart(2, "0")),
    el("h4", "", title),
    el("span", "evidence-badge", status),
    el("code", "", source),
    el("p", "", note),
  );
  parent.append(card);
}
function renderTurns(parent, turns, latestIndex, hits = []) {
  if (!turns?.length) {
    parent.append(
      el(
        "p",
        "detail-context",
        "此记录未保存消息数组，无法可靠还原角色；请查看历史摘要。",
      ),
    );
    return;
  }
  for (const turn of turns) {
    const box = el(
      "details",
      "message-turn " +
        (["system", "developer", "user", "assistant", "tool"].includes(
          turn.role,
        )
          ? turn.role
          : "unknown"),
    );
    box.open = turn.index === latestIndex || turns.length < 3;
    const heading = el("summary");
    const turnHits = hits.filter((h) => h.message_index === turn.index);
    if (turnHits.length)
      heading.append(el("span", "tag", turnHits.length + " 个 PII 命中"));
    heading.append(
      el("span", "role-label", String(turn.role).toUpperCase()),
      el("span", "turn-index", "#" + turn.index),
      el("span", "turn-preview", turn.content?.slice(0, 110) || "[无文本内容]"),
    );
    box.append(heading, el("pre", "", turn.content || "[无文本内容]"));
    if (turn.tool_calls)
      box.append(
        el(
          "p",
          "detail-context",
          "包含 " + turn.tool_calls + " 个工具调用；调用体见原始快照。",
        ),
      );
    parent.append(box);
  }
}
function renderDetail(data) {
  const scan = data.scan,
    related = data.related || [],
    before =
      scan.event_type === "beforeRequestHook"
        ? scan
        : data.correlation?.ambiguous
          ? null
          : related.find((r) => r.event_type === "beforeRequestHook"),
    after =
      scan.event_type === "afterRequestHook"
        ? scan
        : data.correlation?.ambiguous
          ? null
          : related.find((r) => r.event_type === "afterRequestHook");
  const b = before?.payload?.observation || {},
    a = after?.payload?.observation || {},
    o = scan.payload?.observation || {},
    root = $("detail-body");
  o.metadata = o.metadata || o.snapshot?.metadata || {};
  root.replaceChildren();
  root.append(
    el(
      "p",
      "detail-context",
      scan.trace_id
        ? "TRACE " +
            scan.trace_id +
            " · 按相同 Trace 关联；会话内每次调用分别记录。"
        : "未提供 Trace ID · 此记录不能与其他阶段可靠关联。",
    ),
  );
  const identity = scan.payload?.identity || {};
  const ids = el("div", "detail-card");
  detailRow(
    ids,
    "网关 Trace ID",
    identity.gateway_trace_id || "未单独记录（历史数据不能确认来源）",
  );
  detailRow(
    ids,
    "应用 Trace ID",
    identity.application_trace_id || o.metadata.trace_id,
  );
  detailRow(
    ids,
    "会话 ID（不用于配对）",
    identity.session_id || o.metadata.session_id,
  );
  detailRow(
    ids,
    "输入 / 输出关联",
    data.correlation?.ambiguous
      ? "同 Trace 存在多个候选，未自动配对"
      : data.correlation?.paired_scan_id
        ? "已关联记录 #" + data.correlation.paired_scan_id
        : "尚未找到另一阶段；可能尚未到达或未传 Trace",
  );
  detailRow(ids, "用于关联的 Trace ID", scan.trace_id);
  if (related.length > 1) {
    const links = el("div");
    for (const record of related.filter((r) => r.id !== scan.id)) {
      const button = el(
        "button",
        "quiet",
        "#" +
          record.id +
          " · " +
          (record.event_type === "afterRequestHook" ? "输出" : "输入") +
          " · " +
          dateParts(record.timestamp).join(" "),
      );
      button.onclick = () => details(record);
      links.append(button);
    }
    ids.append(links);
  }
  root.append(ids);
  const nav = el("div", "detail-tabs");
  nav.setAttribute("role", "tablist");
  nav.setAttribute("aria-label", "日志详情视图");
  root.append(nav);
  const panels = {};
  for (const [key, name] of [
    ["flow", "请求链路与判定"],
    ["messages", "消息与内容对照"],
    ["source", "Webhook 原始快照"],
  ]) {
    const button = el("button", key === "flow" ? "active" : "", name);
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", key === "flow" ? "true" : "false");
    nav.append(button);
    const panel = el(
      "div",
      "detail-tab-panel" + (key === "flow" ? "" : " hidden"),
    );
    panel.setAttribute("role", "tabpanel");
    panels[key] = panel;
    root.append(panel);
    button.onclick = () => {
      for (const [k, p] of Object.entries(panels))
        p.classList.toggle("hidden", k !== key);
      for (const n of nav.children) {
        n.classList.toggle("active", n === button);
        n.setAttribute("aria-selected", n === button ? "true" : "false");
      }
    };
  }
  const flow = panels.flow,
    grid = el("div", "source-grid");
  flow.append(grid);
  sourceCard(
    grid,
    1,
    "客户端原始请求",
    "未单独上报",
    "Client → Gateway",
    "Webhook 没有客户端入站抓包；网关快照不能等同于客户端原始报文。",
  );
  sourceCard(
    grid,
    2,
    "网关输入检查快照",
    b.snapshot ? "已采集" : before ? "仅历史摘要" : "尚未收到",
    "beforeRequestHook · request.json",
    b.snapshot
      ? "保留 messages 角色、顺序、参数和重复消息。"
      : "需要新的输入检查记录。",
    !!b.snapshot,
  );
  sourceCard(
    grid,
    3,
    "LLM 实际接收内容",
    "未提供接收确认",
    "Gateway → LLM",
    "放行不等于 LLM 已接收。可在内容对照中查看网关两个检查阶段的请求快照。",
  );
  sourceCard(
    grid,
    4,
    "网关收到的 LLM 响应",
    a.snapshot ? "已收到输出事件" : "尚未观测",
    "afterRequestHook · response.json",
    a.snapshot
      ? "显示网关回传的响应快照；不声称是原始网络字节。"
      : "未观测到输出检查事件，不填充模型响应。",
    !!a.snapshot,
  );
  sourceCard(
    grid,
    5,
    "Webhook 检查判定",
    scan.outcome === "allowed"
      ? "允许"
      : scan.outcome === "blocked"
        ? "阻断"
        : "检查未完成",
    "verdict + data",
    "这是本地检查结论，网关最终动作取决于 SCM 策略。",
    true,
  );
  sourceCard(
    grid,
    6,
    "客户端实际收到内容",
    "未提供接收确认",
    "Gateway → Client",
    "当前 Webhook 没有收到客户端送达回执或最终返回报文。",
  );
  const latest = section(flow, "本轮内容 · 保留字段来源");
  const latestCard = el("div", "detail-card");
  latest.append(latestCard);
  latestCard.append(
    el(
      "span",
      "evidence-badge",
      scan.event_type === "afterRequestHook"
        ? "response.json / response.text"
        : "request.json.messages · 最后一个 user",
    ),
  );
  latestCard.append(
    el(
      "pre",
      "current-prompt",
      scan.event_type === "afterRequestHook"
        ? scan.payload?.content?.response || scan.summary
        : o.latest_user?.content || scan.summary,
    ),
  );
  const historicalHits = (scan.payload?.pii_sources || []).filter(
    (h) => !h.is_latest_user,
  );
  if (historicalHits.length)
    flow.append(
      el(
        "p",
        "source-warning",
        "本次 PII 命中中有 " +
          historicalHits.length +
          " 项来自历史或非本轮 user 消息；本轮摘要不代表完整扫描范围。请到消息视图查看命中角色。",
      ),
    );
  const warning = o.duplicate_adjacent_indexes?.length;
  if (warning)
    flow.append(
      el(
        "p",
        "source-warning",
        "网关快照中发现 " +
          warning +
          " 组相邻同角色、同内容消息。界面提示重复但不删除，不改变实际检测输入。",
      ),
    );
  const guards = el("div", "guard-grid");
  flow.append(guards);
  guardCard(guards, before, "input");
  guardCard(guards, after, "output");
  const timingBlock = section(flow, "TIMING & REQUEST CONTEXT"),
    timing = el("div", "detail-card");
  timingBlock.append(timing);
  const t = scan.payload?.timing || {};
  detailRow(timing, "Webhook 总耗时", scan.latency_ms + " ms");
  for (const [label, key] of [
    ["Qwen HTTP 调用", "qwen_request_ms"],
    ["Qwen 模型推理", "qwen_inference_ms"],
    ["Presidio 检测", "presidio_ms"],
    ["结构化快照遮盖", "snapshot_masking_ms"],
  ])
    detailRow(
      timing,
      label,
      t[key] !== undefined ? t[key] + " ms" : "未执行 / 历史未采集",
    );
  detailRow(
    timing,
    "LLM / 网关端到端耗时",
    "未上报；本地检查耗时不能替代端到端耗时",
  );
  detailRow(timing, "网关请求模型", o.gateway_request_model || scan.model);
  detailRow(timing, "响应上报模型", a.response_model);
  detailRow(
    timing,
    "Provider / Request type",
    [o.provider, o.request_type].filter(Boolean).join(" / ") || null,
  );
  detailRow(
    timing,
    "流式请求",
    o.stream === true
      ? "是（stream:true）"
      : o.stream === false
        ? "否（stream:false）"
        : "未上报",
  );
  detailRow(timing, "请求参数", JSON.stringify(o.parameters || {}));
  detailRow(
    timing,
    "业务 / 会话",
    (o.metadata?.feature || "未上报") +
      " / " +
      (o.metadata?.session_id || "未上报"),
  );
  detailRow(
    timing,
    "请求已变换",
    o.request_is_transformed === true
      ? "网关上报 isTransformed:true"
      : o.request_is_transformed === false
        ? "网关上报 isTransformed:false"
        : "未上报",
  );
  const usage = after?.payload?.usage || scan.payload?.usage || {};
  detailRow(
    timing,
    "上报 Tokens（in / out）",
    usage.prompt_tokens !== undefined || usage.completion_tokens !== undefined
      ? (usage.prompt_tokens ?? "—") + " / " + (usage.completion_tokens ?? "—")
      : "未上报",
  );
  detailRow(
    timing,
    "Config · Workspace",
    (scan.payload?.config_id || "未上报") +
      " · " +
      (scan.payload?.workspace_id || "未上报"),
  );
  const conversation = section(panels.messages, "网关请求中的完整对话");
  conversation.append(
    el(
      "p",
      "detail-context",
      "消息来自 " +
        (scan.event_type === "afterRequestHook"
          ? "afterRequestHook"
          : "beforeRequestHook") +
        " 的 request.json.messages；用户、助手、系统与工具消息分别显示。",
    ),
  );
  renderTurns(
    conversation,
    o.messages,
    o.latest_user?.index,
    scan.payload?.pii_sources || [],
  );
  if (!o.messages)
    conversation.append(
      el("pre", "", scan.payload?.content?.prompt || scan.summary),
    );
  contentPair(
    panels.messages,
    "本轮文本来源对照",
    "request.text · 网关便捷文本",
    o.request_text,
    "messages 中最后一个 user",
    o.latest_user?.content,
  );
  const guardInput = section(
    panels.messages,
    "检测模型输入 · 与业务 LLM 接收内容区分",
  );
  const guarded = scan.payload?.guard_input;
  guardInput.append(
    el(
      "p",
      "detail-context",
      guarded
        ? guarded.executed
          ? "本地 Qwen3Guard 请求已执行；下方为检测模型输入的日志副本。"
          : "PII 优先阻断，Qwen3Guard 未执行。"
        : "历史记录：未采集检测模型请求结构。",
    ),
  );
  guardInput.append(
    el(
      "pre",
      "",
      guarded ? JSON.stringify(guarded.messages, null, 2) : "未采集",
    ),
  );
  const snapshots = section(panels.messages, "输入 / 输出阶段的请求快照对照"),
    pair = el("div", "content-grid");
  snapshots.append(pair);
  for (const [heading, obs] of [
    ["输入阶段 request.json", b],
    ["输出阶段 request.json", a],
  ]) {
    const card = el("div", "detail-card content-card");
    card.append(
      el("h4", "", heading),
      el(
        "pre",
        "",
        obs.snapshot
          ? JSON.stringify(
              obs.snapshot.request?.json || obs.snapshot.request || {},
              null,
              2,
            )
          : "未采集此阶段的结构化快照",
      ),
    );
    pair.append(card);
  }
  const responseBlock = section(
    panels.messages,
    "网关响应快照 · 与客户端送达确认区分",
  );
  responseBlock.append(
    el(
      "pre",
      "",
      a.snapshot
        ? JSON.stringify(
            a.snapshot.response?.json || a.snapshot.response || {},
            null,
            2,
          )
        : "未收到 afterRequestHook；不能由下一轮聊天历史反推这一轮的原始 LLM 响应。",
    ),
  );
  const source = panels.source;
  source.append(
    el(
      "p",
      "detail-context",
      "这是 AI Gateway 发给 Webhook 的 JSON 日志副本：移除凭据字段，并遮盖 Presidio 检出的 PII。它不是客户端到网关的原始 HTTP 报文。",
    ),
  );
  if (o.snapshot_truncated)
    source.append(
      el("p", "source-warning", "快照超过记录限额，部分内容未保存。"),
    );
  if (o.capture_error)
    source.append(el("p", "source-warning", o.capture_error));
  source.append(
    el(
      "pre",
      "source-json",
      o.snapshot
        ? JSON.stringify(o.snapshot, null, 2)
        : "历史记录没有保存 Webhook 请求体，无法补造原始字段。",
    ),
  );
  if (o.top_level_fields) {
    const schema = section(source, "实际字段结构");
    schema.append(
      el(
        "pre",
        "",
        JSON.stringify(
          {
            top_level: o.top_level_fields,
            request: o.request_fields,
            request_json: o.request_json_fields,
            response: o.response_fields,
          },
          null,
          2,
        ),
      ),
    );
  }
  if (scan.pii?.length) {
    const hits = section(source, "PII 命中 · 位置基于扫描文本，不是本轮摘要");
    const card = el("div", "detail-card");
    hits.append(card);
    for (const hit of scan.pii)
      detailRow(
        card,
        hit.entity_type,
        "字符 [" +
          hit.start +
          ", " +
          hit.end +
          ") · Presidio score " +
          hit.score,
      );
  }
  $("detail-json").textContent = JSON.stringify(data, null, 2);
}

async function details(item) {
  $("details").dataset.scanId = String(item.id);
  $("detail-id").textContent = "#" + item.id;
  const meta = $("detail-meta");
  meta.replaceChildren();
  for (const value of [
    outcomes[item.outcome],
    dateParts(item.timestamp).join(" "),
    item.latency_ms + " ms",
    "Webhook HTTP " + item.http_status,
  ])
    meta.append(el("span", "", value));
  $("detail-body").replaceChildren(el("p", "muted", "正在加载检查详情…"));
  $("detail-json").textContent = "";
  if (!$("details").open) $("details").showModal();
  try {
    const response = await fetch("/api/logs/" + item.id, { cache: "no-store" });
    if (response.status === 401) {
      $("details").close();
      showLogin("会话已失效，请重新登录。");
      return;
    }
    if (!response.ok)
      throw new Error("详情加载失败（HTTP " + response.status + "）");
    const data = await response.json();
    if ($("details").dataset.scanId === String(item.id)) renderDetail(data);
  } catch (error) {
    $("detail-body").replaceChildren(el("p", "error", error.message));
  }
}

async function load() {
  if (pending) {
    queued = true;
    return;
  }
  pending = true;
  $("refresh").disabled = true;
  try {
    const query = new URLSearchParams({
      limit: $("limit").value,
      outcome: $("outcome").value,
      q: $("search").value,
      offset: String(offset),
    });
    const response = await fetch("/api/logs?" + query, { cache: "no-store" });
    if (response.status === 401) {
      showLogin();
      return;
    }
    if (!response.ok)
      throw new Error("日志读取失败（HTTP " + response.status + "）");
    const data = await response.json();
    showDashboard();
    items = data.items;
    total = data.total;
    if (offset >= total && offset > 0) {
      offset = 0;
      queued = true;
      return;
    }
    $("total").textContent = total;
    $("blocked").textContent = data.counts.blocked || 0;
    $("allowed").textContent = data.counts.allowed || 0;
    $("pii").textContent = data.pii_requests || 0;
    $("errors").textContent =
      (data.counts.error || 0) + (data.counts.rejected || 0);
    $("updated").textContent = dateParts(data.updated_at)[1];
    fetch("/api/metrics")
      .then((r) => (r.ok ? r.json() : null))
      .then((m) => {
        if (m)
          $("runtime-metrics").textContent =
            "近 24 小时：" +
            m.scans +
            " 次阶段检查 · 内容阻断 " +
            m.blocked +
            " · 调用异常 " +
            m.errors +
            " · P50 " +
            (m.latency_p50_ms ?? "—") +
            " ms · P95 " +
            (m.latency_p95_ms ?? "—") +
            " ms";
      })
      .catch(() => {
        $("runtime-metrics").textContent = "运行指标暂不可用";
      });
    $("error").classList.add("hidden");
    $("connection").textContent = "日志已连接";
    render();
  } catch (error) {
    $("error").textContent = error.message;
    $("error").classList.remove("hidden");
    $("connection").textContent = "连接异常";
  } finally {
    pending = false;
    $("refresh").disabled = false;
    if (queued) {
      queued = false;
      load();
    }
  }
}
$("login-form").onsubmit = async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  button.disabled = true;
  $("login-error").textContent = "";
  try {
    const response = await fetch("/api/logs/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: $("token").value }),
    });
    if (!response.ok)
      throw new Error(
        response.status === 401
          ? "Token 无效，请使用 LOGS_TOKEN。"
          : "登录失败，请稍后重试。",
      );
    $("token").value = "";
    await load();
  } catch (error) {
    $("login-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
};
$("logout").onclick = async () => {
  await fetch("/api/logs/logout", { method: "POST" });
  items = [];
  $("rows").replaceChildren();
  showLogin();
};
for (const id of ["limit", "outcome"])
  $(id).onchange = () => {
    offset = 0;
    load();
  };
let debounce;
$("search").oninput = () => {
  clearTimeout(debounce);
  debounce = setTimeout(() => {
    offset = 0;
    load();
  }, 300);
};
$("refresh").onclick = () => load();
$("timezone").onchange = () => render();
$("prev").onclick = () => {
  offset = Math.max(0, offset - Number($("limit").value));
  load();
};
$("next").onclick = () => {
  offset += Number($("limit").value);
  load();
};
$("close-details").onclick = () => $("details").close();
$("details").onclick = (event) => {
  if (event.target === $("details")) {
    const box = $("details").getBoundingClientRect();
    if (
      event.clientX < box.left ||
      event.clientX > box.right ||
      event.clientY < box.top ||
      event.clientY > box.bottom
    )
      $("details").close();
  }
};
setInterval(() => {
  if (
    $("auto").checked &&
    !$("dashboard").classList.contains("hidden") &&
    !document.hidden
  )
    load();
}, 10000);
load();

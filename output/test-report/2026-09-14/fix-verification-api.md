# CasePilot 缺陷修复 API 复验记录

- 复验日期：2026-09-14（Asia/Shanghai）
- 基础地址：`http://127.0.0.1:8000`
- 鉴权头已脱敏；`caller.example` 是不可达测试占位域名。

## 1. BUG-002：case-summary 稳定深链

连续调用：

```http
GET /case-projects/CP-00040/case-summary
Authorization: Bearer ***
```

请求 body：`null`

```http
POST /case-projects/CP-00040/case-summary
Authorization: Bearer ***
```

请求 body：`null`

两次响应均为 `200`，业务快照完全相等，且返回相同链接：

```json
{
  "case_project_id": "CP-00040",
  "case_generation_id": "CASE-SESSION-00071",
  "generation_status": "approved",
  "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00040?access_token=<redacted-stable-token>",
  "case_count": 3
}
```

结论：项目链接到期时间已持久化；同一有效期内 GET/POST 不再按当前秒重新签名。

## 2. BUG-003：Playlist generation ID 回传

### 2.1 创建深链会话

`POST /case-projects/CP-00040/playlist-creation-sessions`

Request body：

```json
{
  "creator": "demo",
  "test_target": {
    "target_type": "fr_test",
    "target_id": 1368775591,
    "target_key": "FR-REVIEW-1368775591",
    "title": "设备所有者说话人分离与弱网恢复",
    "linked_fr_ids": [],
    "linked_qpm_ids": []
  },
  "case_collections": [
    {
      "case_project_id": "CP-00040",
      "case_generation_id": "CASE-SESSION-00071"
    }
  ],
  "playlist": {
    "name": "修复复验播放列表-20260914",
    "case_ids": ["CP-00040-CASE-001", "CP-00040-CASE-002"],
    "execution_notes": "验证 generation ID 回传"
  },
  "callback_url": "https://caller.example/hooks/playlist-fixed",
  "callback_events": ["playlist-created"],
  "callback_correlation_id": "acceptance-fix-20260914",
  "callback_context": {
    "request_id": "REQ-FIX-20260914-001"
  }
}
```

Response `201`：

```json
{
  "playlist_creation_id": "a28aa506-d052-4eb7-923b-6a95374b47ca",
  "creation_status": "pending_user_action",
  "case_platform_url": "http://127.0.0.1:3000/?playlist_creation_id=a28aa506-d052-4eb7-923b-6a95374b47ca",
  "expires_at": "2026-09-14T09:34:37.031093Z"
}
```

### 2.2 完成 Playlist

`POST /api/v1/playlist-creation-sessions/a28aa506-d052-4eb7-923b-6a95374b47ca/complete`

Request body：

```json
{
  "name": "修复复验播放列表-20260914",
  "description": "BUG-003 fix verification",
  "case_ids": ["CP-00040-CASE-001", "CP-00040-CASE-002"],
  "execution_notes": "验证 generation ID 回传"
}
```

Response `201` 关键字段：

```json
{
  "creation_status": "created",
  "playlist": {
    "playlist_id": "59aef4fd-b34b-4ccb-832c-67cf78619010",
    "case_count": 2,
    "case_collections": [
      {
        "collection_id": "4b095a1d-d9d2-47f7-b700-a1e6257df652",
        "case_project_id": "CP-00040",
        "case_generation_id": "CASE-SESSION-00071"
      }
    ]
  }
}
```

durable outbox 中 `playlist-created` 回调关键字段：

```json
{
  "event_id": "8ad588c0-f901-43c2-b794-003863020614",
  "playlist_creation_id": "a28aa506-d052-4eb7-923b-6a95374b47ca",
  "callback_correlation_id": "acceptance-fix-20260914",
  "callback_context": {
    "request_id": "REQ-FIX-20260914-001"
  },
  "playlist": {
    "playlist_id": "59aef4fd-b34b-4ccb-832c-67cf78619010",
    "case_collections": [
      {
        "case_project_id": "CP-00040",
        "case_generation_id": "CASE-SESSION-00071"
      }
    ]
  }
}
```

结论：完成响应和回调均保留请求中的 `CASE-SESSION-00071`。

## 3. BUG-001：真实生成阶段记录

- 会话：`cb5c0300-d686-4d3c-ab94-2d48e9c3fa0b`
- 最终任务：`a5542174-878c-4fcd-b31c-c5e8d5f4ccb0`
- 用户选择模型：`ark-code-latest`
- 终态：`completed`
- 产物：10 条候选用例；质量评分 76；未纳入正式集合。

```json
[
  {"stage": "context.prepared", "model": "openai_compatible:doubao-embedding-vision", "latency_ms": 0},
  {"stage": "requirement.analyzed", "model": "ark-code-latest", "latency_ms": 53440},
  {"stage": "feature.generated", "model": "ark-code-latest", "latency_ms": 109465},
  {"stage": "test_point.generated", "model": "doubao-seed-2.0-lite", "latency_ms": 51763},
  {"stage": "test_case.generated", "model": "doubao-seed-2.0-lite", "latency_ms": 62183},
  {"stage": "quality.completed", "model": "deterministic-rules-v1", "latency_ms": 0}
]
```

结论：首选模型超时后自动切换默认模型，测试点、候选用例和质量检查完整落库，未再以 `APITimeoutError` 终止。

## 4. PERF-001：生成耗时与差量质量修复复验

### 4.1 启动真实模型复验

```http
POST /api/v1/workspaces/cb5c0300-d686-4d3c-ab94-2d48e9c3fa0b/test-briefs/confirm
Content-Type: application/json
```

Request body：

```json
{
  "version": 3,
  "model_id": "local"
}
```

Response `202` 返回任务：

```json
{
  "job_id": "b1e717be-2405-4b91-99c8-9f90653bc8f5"
}
```

45 秒快速降级生效后的阶段记录：

```json
[
  {"stage": "requirement.analyzed", "model": "doubao-seed-2.0-lite", "latency_ms": 94967},
  {"stage": "feature.generated", "model": "doubao-seed-2.0-lite", "latency_ms": 87602},
  {"stage": "test_point.generated", "model": "doubao-seed-2.0-lite", "latency_ms": 139720},
  {"stage": "test_case.generated", "model": "doubao-seed-2.0-lite", "latency_ms": 174123}
]
```

同输入、优化范围扩大前，需求和功能点分别为 `150851 ms`、`168611 ms`；扩大到全部结构化阶段后分别降至 `94967 ms`、`87602 ms`，合计减少 `136893 ms`。阶段延迟现在包含失败模型等待与默认模型生成时间，不再低报墙钟耗时。

### 4.2 差量质量修复重试

初始候选仅有一个质量错误：测试点 `TP-GEN-001` 引用了未生成的功能点。旧修复契约不能新增功能点，并把整批对象再次交给模型，导致修复输出 JSON 截断。修复后调用：

```http
POST /api/v1/generation-jobs/b1e717be-2405-4b91-99c8-9f90653bc8f5/retry
```

Request body：`null`

Response `202`；重试复用需求、功能点、测试点和用例四个已完成阶段，只执行新的差量修复。最终结果：

```json
{
  "job_id": "b1e717be-2405-4b91-99c8-9f90653bc8f5",
  "status": "completed",
  "retry_wall_time_ms": 40800,
  "candidate_count": 8,
  "quality": {
    "passed": true,
    "score": 100,
    "repair_rounds": 1,
    "issues": []
  },
  "enhancement_stage": {
    "model": "ark-code-latest",
    "latency_ms": 37475,
    "input_tokens": 5117,
    "output_tokens": 1302
  }
}
```

候选仍停留在人工评审阶段，没有调用候选提交接口，也没有写入正式集合。

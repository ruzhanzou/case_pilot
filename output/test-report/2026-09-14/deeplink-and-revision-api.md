# CasePilot 深链与修订 API 调用记录

- 执行日期：2026-09-14（Asia/Shanghai）
- 基础地址：`http://localhost:8000`
- 鉴权信息均已脱敏；示例回调域名为不可达的测试占位域名，因此实际投递失败不计为产品缺陷。

## 1. 创建 Playlist 深链会话

`POST /case-projects/CP-00040/playlist-creation-sessions`

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
    "name": "深链验收播放列表-20260914",
    "case_ids": ["CP-00040-CASE-001", "CP-00040-CASE-002"],
    "execution_notes": "验证深链预填、Playlist保存与执行任务入口"
  },
  "callback_url": "https://caller.example/hooks/playlist",
  "callback_events": ["playlist-created"],
  "callback_correlation_id": "acceptance-20260914",
  "callback_context": {
    "request_id": "REQ-20260914-001",
    "return_url": "https://caller.example/test-web"
  }
}
```

响应 `201`：

```json
{
  "playlist_creation_id": "b33848cf-a02d-4311-bdd3-fdc69ba0eec4",
  "creation_status": "pending_user_action",
  "case_platform_url": "http://127.0.0.1:3000/?playlist_creation_id=b33848cf-a02d-4311-bdd3-fdc69ba0eec4",
  "expires_at": "2026-09-14T07:56:22.951976Z"
}
```

浏览器登录后自动进入“创建多人执行任务”，预填 Playlist 名称和 2 条用例；保存后会话状态为 `created`，Playlist ID 为 `e2c92f09-04ec-4624-9cde-56cc61636024`。

## 2. 修改正式用例并创建新 Revision

`PATCH /api/v1/test-cases/56b868a7-af71-4244-bc63-e0a80c200bcb`

```json
{
  "base_revision_id": "d2d37ba2-ac30-4b31-a926-041765417a8c",
  "title": "FR-REVIEW-1368775591：验证核心成功路径（验收修订）",
  "module": "设备所有者说话人分离与弱网恢复",
  "priority": "P1",
  "case_type": "功能",
  "tags": ["integration-mock", "L0", "acceptance-20260914"],
  "preconditions": ["目标环境可用", "TestTool 已完成用户绑定"],
  "steps": [
    {
      "id": "98e04091-e497-4917-afd6-d5fa5beb7587",
      "action": "执行 L0 阶段场景",
      "expected": "结果符合需求"
    }
  ],
  "source": "FR-REVIEW-1368775591",
  "source_refs": [
    {
      "source_id": null,
      "document_id": null,
      "chunk_id": null,
      "label": "FR-REVIEW-1368775591",
      "locator": "fr_test:1368775591",
      "excerpt": "Fixed integration mock prompt"
    }
  ],
  "execution_level": "L0",
  "test_domains": ["Function"],
  "automation_type": "manual"
}
```

响应 `200`：当前 Revision 从 V1 更新为 V2，`current_revision_id` 为 `86dbfdfd-7789-4e5b-9e02-2bb6d59fcc04`。

## 3. 冻结 Revision 校验

执行任务 `4f916945-5125-4b71-9bc9-49e2a94e492e` 创建于修改之前。修改正式用例后数据库校验结果：

```json
{
  "execution_revision_id": "d2d37ba2-ac30-4b31-a926-041765417a8c",
  "execution_revision_number": 1,
  "execution_title": "FR-REVIEW-1368775591：验证核心成功路径",
  "current_revision_id": "86dbfdfd-7789-4e5b-9e02-2bb6d59fcc04",
  "current_revision_number": 2,
  "current_title": "FR-REVIEW-1368775591：验证核心成功路径（验收修订）"
}
```

结论：执行任务继续引用 V1，未被正式用例 V2 修改污染。

## 4. Playlist 回调记录

回调事件已进入 durable outbox，`event_type=playlist-created`，correlation/context 均原样回传。由于测试使用 `caller.example` 占位域名，投递处于重试状态。

首次验收载荷中 `case_collections[0].case_generation_id` 为 `null`，与创建会话请求中的 `CASE-SESSION-00071` 不一致，曾登记为 BUG-003。

修复后重新创建会话 `a28aa506-d052-4eb7-923b-6a95374b47ca` 并完成 Playlist `59aef4fd-b34b-4ccb-832c-67cf78619010`，完成响应及 `playlist-created` 回调中的 `case_generation_id` 均为 `CASE-SESSION-00071`。详细 request body、response 和回调载荷见 [`fix-verification-api.md`](./fix-verification-api.md)。BUG-003 复验通过。

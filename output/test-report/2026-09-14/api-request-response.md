# Case Service 接口逐请求测试报告

- 执行时间：2026-09-14T06:52:55.450939+00:00
- 生成模式：mock
- 结果：PASSED
- Case Project：CP-00040
- Generation：CASE-SESSION-00071
- Task：TASK-00025
- 客户端请求数：14
- 异步回调数：0

## 客户端请求与返回

### 1. 创建空用例集合

耗时：34 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/case-projects",
  "headers": {
    "Authorization": "Bearer ***"
  },
  "body": {
    "source_system": "test_web",
    "test_target": {
      "target_type": "fr_test",
      "target_id": 1368775591,
      "target_key": "FR-REVIEW-1368775591",
      "title": "设备所有者说话人分离与弱网恢复",
      "linked_fr_ids": [],
      "linked_qpm_ids": []
    },
    "test_context": {
      "description": "验证设备所有者检测、弱网恢复与长时间稳定性",
      "platform": "Android",
      "build_version": "review-real-1"
    }
  }
}
```

返回：

```json
{
  "status": 201,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "case_project_id": "CP-00040",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00040?access_token=<redacted-token-a>"
  }
}
```

### 2. 启动异步用例生成

耗时：33 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/case-projects/CP-00040/case-generation-jobs",
  "headers": {
    "Authorization": "Bearer ***"
  },
  "body": {
    "test_target": {
      "target_type": "fr_test",
      "target_id": 1368775591,
      "target_key": "FR-REVIEW-1368775591",
      "title": "设备所有者说话人分离与弱网恢复",
      "linked_fr_ids": [],
      "linked_qpm_ids": []
    },
    "test_context": {
      "network_profiles": [
        "offline",
        "high_jitter"
      ]
    },
    "model_id": "auto"
  }
}
```

返回：

```json
{
  "status": 202,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "case_generation_id": "CASE-SESSION-00071",
    "case_generation_status": "generating",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00040?access_token=<redacted-token-a>",
    "callback_correlation_id": null
  }
}
```

### 3. 轮询生成状态 #1

耗时：41 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00040/case-summary",
  "headers": {
    "Authorization": "Bearer ***"
  },
  "body": null
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "target_type": "fr_test",
    "target_id": 1368775591,
    "case_project_id": "CP-00040",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00040?access_token=<redacted-token-a>",
    "case_generation_id": "CASE-SESSION-00071",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-14T06:52:55.557964Z",
    "cases": {}
  }
}
```

### 4. 轮询生成状态 #2

耗时：18 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00040/case-summary",
  "headers": {
    "Authorization": "Bearer ***"
  },
  "body": null
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "target_type": "fr_test",
    "target_id": 1368775591,
    "case_project_id": "CP-00040",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00040?access_token=<redacted-token-b>",
    "case_generation_id": "CASE-SESSION-00071",
    "generation_status": "approved",
    "generation_updated_at": "2026-09-14T06:52:55.633975Z",
    "cases": {
      "CP-00040-CASE-001": {
        "stage": "L0",
        "test_domain": [
          "Function"
        ],
        "title": "FR-REVIEW-1368775591：验证核心成功路径",
        "automation_type": "manual"
      },
      "CP-00040-CASE-002": {
        "stage": "L2",
        "test_domain": [
          "Reliability"
        ],
        "title": "FR-REVIEW-1368775591：验证异常输入与恢复路径",
        "automation_type": "automated"
      },
      "CP-00040-CASE-003": {
        "stage": "L4",
        "test_domain": [
          "Stability"
        ],
        "title": "FR-REVIEW-1368775591：验证长时间运行与跨系统回归",
        "automation_type": "automated"
      }
    }
  }
}
```

### 5. POST 方式读取完整用例快照

耗时：16 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/case-projects/CP-00040/case-summary",
  "headers": {
    "Authorization": "Bearer ***"
  },
  "body": null
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "target_type": "fr_test",
    "target_id": 1368775591,
    "case_project_id": "CP-00040",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00040?access_token=<redacted-token-b>",
    "case_generation_id": "CASE-SESSION-00071",
    "generation_status": "approved",
    "generation_updated_at": "2026-09-14T06:52:55.633975Z",
    "cases": {
      "CP-00040-CASE-001": {
        "stage": "L0",
        "test_domain": [
          "Function"
        ],
        "title": "FR-REVIEW-1368775591：验证核心成功路径",
        "automation_type": "manual"
      },
      "CP-00040-CASE-002": {
        "stage": "L2",
        "test_domain": [
          "Reliability"
        ],
        "title": "FR-REVIEW-1368775591：验证异常输入与恢复路径",
        "automation_type": "automated"
      },
      "CP-00040-CASE-003": {
        "stage": "L4",
        "test_domain": [
          "Stability"
        ],
        "title": "FR-REVIEW-1368775591：验证长时间运行与跨系统回归",
        "automation_type": "automated"
      }
    }
  }
}
```

### 6. 创建待确认执行任务

耗时：45 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/case-projects/CP-00040/tasks",
  "headers": {
    "Authorization": "Bearer ***"
  },
  "body": {
    "test_target": {
      "target_type": "fr_test",
      "target_id": 1368775591,
      "target_key": "FR-REVIEW-1368775591",
      "title": "设备所有者说话人分离与弱网恢复",
      "linked_fr_ids": [],
      "linked_qpm_ids": []
    },
    "test_context": {
      "build_version": "review-real-1"
    },
    "task_context": {
      "tester": "executor@casepilot.local",
      "execution_notes": "执行 L2 累计范围并同步结果",
      "execution_level": "L2"
    },
    "task_request_id": "20c9625a-4fd9-4888-a0d4-8f4768072c45",
    "case_generation_id": "CASE-SESSION-00071"
  }
}
```

返回：

```json
{
  "status": 202,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "task_request_id": "20c9625a-4fd9-4888-a0d4-8f4768072c45",
    "test_task_id": "TASK-00025",
    "execution_status": "pending_confirmation",
    "case_platform_url": "http://127.0.0.1:3000/playlists/b4101aa1-1607-471c-a0a8-a9a3d4c7388d?task_request_id=20c9625a-4fd9-4888-a0d4-8f4768072c45&case_project_id=CP-00040"
  }
}
```

### 7. 登录 CasePilot 确认人

耗时：147 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/api/v1/auth/login",
  "headers": {},
  "body": {
    "email": "demo@casepilot.local",
    "password": "***"
  }
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "id": "7727e3f3-92c6-422c-8d9e-4fb44e5a84bb",
    "email": "demo@casepilot.local",
    "display_name": "体验用户",
    "spaces": [
      {
        "id": "6a257229-e17f-4baf-9f52-ba2c502ece0e",
        "name": "体验用户的质量空间",
        "description": "CasePilot 本地验收空间",
        "role": "owner"
      }
    ]
  }
}
```

### 8. 确认 Playlist 并冻结 ExecutionRun

耗时：122 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/api/v1/integration-task-requests/20c9625a-4fd9-4888-a0d4-8f4768072c45/confirm",
  "headers": {},
  "body": {
    "execution_level": "L2"
  }
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "test_task_id": "TASK-00025",
    "task_request_id": "20c9625a-4fd9-4888-a0d4-8f4768072c45",
    "case_project_id": "CP-00040",
    "case_generation_id": "CASE-SESSION-00071",
    "target_type": "fr_test",
    "target_id": 1368775591,
    "target_key": "FR-REVIEW-1368775591",
    "task_name": "FR-REVIEW-1368775591 execution",
    "tester": "executor@casepilot.local",
    "execution_notes": "执行 L2 累计范围并同步结果",
    "execution_level": "L2",
    "execution_status": "confirmed",
    "updated_at": "2026-09-14T06:52:57.950092Z",
    "cases_complete": true,
    "cases": {
      "CP-00040-CASE-001": {
        "case_id": "CP-00040-CASE-001",
        "title": "FR-REVIEW-1368775591：验证核心成功路径",
        "stage": "L0",
        "test_domain": [
          "Function"
        ],
        "automation_type": "manual",
        "preconditions": [
          "目标环境可用",
          "TestTool 已完成用户绑定"
        ],
        "steps": [
          {
            "id": "98e04091-e497-4917-afd6-d5fa5beb7587",
            "action": "执行 L0 阶段场景",
            "expected": "结果符合需求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-14T06:52:57.900329Z"
      },
      "CP-00040-CASE-002": {
        "case_id": "CP-00040-CASE-002",
        "title": "FR-REVIEW-1368775591：验证异常输入与恢复路径",
        "stage": "L2",
        "test_domain": [
          "Reliability"
        ],
        "automation_type": "automated",
        "preconditions": [
          "目标环境可用",
          "TestTool 已完成用户绑定"
        ],
        "steps": [
          {
            "id": "69be7cbf-58be-42f2-a338-ecd73b059a03",
            "action": "执行 L2 阶段场景",
            "expected": "结果符合需求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-14T06:52:57.900348Z"
      }
    },
    "logs": [],
    "artifacts": [],
    "case_platform_url": "http://127.0.0.1:3000/playlists/b4101aa1-1607-471c-a0a8-a9a3d4c7388d",
    "lease_expires_at": null
  }
}
```

### 9. 按当前用户、target_type 与 case_id 查询任务

耗时：32 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks?target_type=fr_test&case_id=CP-00040-CASE-001",
  "headers": {
    "Authorization": "Bearer ***",
    "X-TestTool-User-ID": "executor@casepilot.local"
  },
  "body": null
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "items": [
      {
        "test_task_id": "TASK-00025",
        "task_request_id": "20c9625a-4fd9-4888-a0d4-8f4768072c45",
        "case_project_id": "CP-00040",
        "case_generation_id": "CASE-SESSION-00071",
        "target_type": "fr_test",
        "target_id": 1368775591,
        "target_key": "FR-REVIEW-1368775591",
        "task_name": "FR-REVIEW-1368775591 execution",
        "tester": "executor@casepilot.local",
        "execution_notes": "执行 L2 累计范围并同步结果",
        "execution_level": "L2",
        "execution_status": "confirmed",
        "updated_at": "2026-09-14T06:52:57.950092Z",
        "cases_complete": true,
        "cases": {
          "CP-00040-CASE-001": {
            "case_id": "CP-00040-CASE-001",
            "title": "FR-REVIEW-1368775591：验证核心成功路径",
            "stage": "L0",
            "test_domain": [
              "Function"
            ],
            "automation_type": "manual",
            "preconditions": [
              "目标环境可用",
              "TestTool 已完成用户绑定"
            ],
            "steps": [
              {
                "id": "98e04091-e497-4917-afd6-d5fa5beb7587",
                "action": "执行 L0 阶段场景",
                "expected": "结果符合需求"
              }
            ],
            "status": "not_run",
            "actual_result": "",
            "completed_step_ids": [],
            "defect_ref": "",
            "logs": [],
            "artifacts": [],
            "updated_at": "2026-09-14T06:52:57.900329Z"
          },
          "CP-00040-CASE-002": {
            "case_id": "CP-00040-CASE-002",
            "title": "FR-REVIEW-1368775591：验证异常输入与恢复路径",
            "stage": "L2",
            "test_domain": [
              "Reliability"
            ],
            "automation_type": "automated",
            "preconditions": [
              "目标环境可用",
              "TestTool 已完成用户绑定"
            ],
            "steps": [
              {
                "id": "69be7cbf-58be-42f2-a338-ecd73b059a03",
                "action": "执行 L2 阶段场景",
                "expected": "结果符合需求"
              }
            ],
            "status": "not_run",
            "actual_result": "",
            "completed_step_ids": [],
            "defect_ref": "",
            "logs": [],
            "artifacts": [],
            "updated_at": "2026-09-14T06:52:57.900348Z"
          }
        },
        "logs": [],
        "artifacts": [],
        "case_platform_url": "http://127.0.0.1:3000/playlists/b4101aa1-1607-471c-a0a8-a9a3d4c7388d",
        "lease_expires_at": null
      }
    ],
    "next_cursor": null
  }
}
```

### 10. TestTool 领取指定任务

耗时：47 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00025/claim",
  "headers": {
    "Authorization": "Bearer ***",
    "X-TestTool-User-ID": "executor@casepilot.local"
  },
  "body": {
    "worker_id": "review-worker",
    "lease_seconds": 300
  }
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "test_task_id": "TASK-00025",
    "task_request_id": "20c9625a-4fd9-4888-a0d4-8f4768072c45",
    "case_project_id": "CP-00040",
    "case_generation_id": "CASE-SESSION-00071",
    "target_type": "fr_test",
    "target_id": 1368775591,
    "target_key": "FR-REVIEW-1368775591",
    "task_name": "FR-REVIEW-1368775591 execution",
    "tester": "executor@casepilot.local",
    "execution_notes": "执行 L2 累计范围并同步结果",
    "execution_level": "L2",
    "execution_status": "running",
    "updated_at": "2026-09-14T06:52:58.017943Z",
    "cases_complete": true,
    "cases": {
      "CP-00040-CASE-001": {
        "case_id": "CP-00040-CASE-001",
        "title": "FR-REVIEW-1368775591：验证核心成功路径",
        "stage": "L0",
        "test_domain": [
          "Function"
        ],
        "automation_type": "manual",
        "preconditions": [
          "目标环境可用",
          "TestTool 已完成用户绑定"
        ],
        "steps": [
          {
            "id": "98e04091-e497-4917-afd6-d5fa5beb7587",
            "action": "执行 L0 阶段场景",
            "expected": "结果符合需求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-14T06:52:57.900329Z"
      },
      "CP-00040-CASE-002": {
        "case_id": "CP-00040-CASE-002",
        "title": "FR-REVIEW-1368775591：验证异常输入与恢复路径",
        "stage": "L2",
        "test_domain": [
          "Reliability"
        ],
        "automation_type": "automated",
        "preconditions": [
          "目标环境可用",
          "TestTool 已完成用户绑定"
        ],
        "steps": [
          {
            "id": "69be7cbf-58be-42f2-a338-ecd73b059a03",
            "action": "执行 L2 阶段场景",
            "expected": "结果符合需求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-14T06:52:57.900348Z"
      }
    },
    "logs": [],
    "artifacts": [],
    "case_platform_url": "http://127.0.0.1:3000/playlists/b4101aa1-1607-471c-a0a8-a9a3d4c7388d",
    "lease_expires_at": "2026-09-14T06:57:58.017943Z",
    "lease_token": "***"
  }
}
```

### 11. TestTool 续租

耗时：22 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00025/heartbeat",
  "headers": {
    "Authorization": "Bearer ***",
    "X-TestTool-User-ID": "executor@casepilot.local",
    "X-Lease-Token": "***"
  },
  "body": {
    "worker_id": "review-worker",
    "lease_seconds": 300
  }
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "test_task_id": "TASK-00025",
    "lease_expires_at": "2026-09-14T06:57:58.066319Z"
  }
}
```

### 12. 上报完整任务与用例状态

耗时：70 ms

请求：

```json
{
  "method": "PATCH",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00025",
  "headers": {
    "Authorization": "Bearer ***",
    "X-TestTool-User-ID": "executor@casepilot.local"
  },
  "body": {
    "update_id": "b5dd1ff0-78a3-4400-8d05-8d3ec85f2cd2",
    "lease_token": "***",
    "status": "completed",
    "updated_at": "2026-09-14T06:53:00.158480+00:00",
    "cases_complete": true,
    "cases": {
      "CP-00040-CASE-001": {
        "status": "passed",
        "updated_at": "2026-09-14T06:53:00.158480+00:00",
        "actual_result": "真实生成用例的 Mock 执行通过",
        "completed_step_ids": [],
        "logs": [
          {
            "level": "info",
            "message": "review execution passed"
          }
        ],
        "artifacts": []
      },
      "CP-00040-CASE-002": {
        "status": "passed",
        "updated_at": "2026-09-14T06:53:00.158480+00:00",
        "actual_result": "真实生成用例的 Mock 执行通过",
        "completed_step_ids": [],
        "logs": [
          {
            "level": "info",
            "message": "review execution passed"
          }
        ],
        "artifacts": []
      }
    },
    "logs": [
      {
        "level": "info",
        "message": "task completed"
      }
    ],
    "artifacts": []
  }
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "test_task_id": "TASK-00025",
    "task_request_id": "20c9625a-4fd9-4888-a0d4-8f4768072c45",
    "case_project_id": "CP-00040",
    "case_generation_id": "CASE-SESSION-00071",
    "target_type": "fr_test",
    "target_id": 1368775591,
    "target_key": "FR-REVIEW-1368775591",
    "task_name": "FR-REVIEW-1368775591 execution",
    "tester": "executor@casepilot.local",
    "execution_notes": "执行 L2 累计范围并同步结果",
    "execution_level": "L2",
    "execution_status": "completed",
    "updated_at": "2026-09-14T06:53:00.158480Z",
    "cases_complete": true,
    "cases": {
      "CP-00040-CASE-001": {
        "case_id": "CP-00040-CASE-001",
        "title": "FR-REVIEW-1368775591：验证核心成功路径",
        "stage": "L0",
        "test_domain": [
          "Function"
        ],
        "automation_type": "manual",
        "preconditions": [
          "目标环境可用",
          "TestTool 已完成用户绑定"
        ],
        "steps": [
          {
            "id": "98e04091-e497-4917-afd6-d5fa5beb7587",
            "action": "执行 L0 阶段场景",
            "expected": "结果符合需求"
          }
        ],
        "status": "passed",
        "actual_result": "真实生成用例的 Mock 执行通过",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [
          {
            "level": "info",
            "message": "review execution passed"
          }
        ],
        "artifacts": [],
        "updated_at": "2026-09-14T06:53:00.158480Z"
      },
      "CP-00040-CASE-002": {
        "case_id": "CP-00040-CASE-002",
        "title": "FR-REVIEW-1368775591：验证异常输入与恢复路径",
        "stage": "L2",
        "test_domain": [
          "Reliability"
        ],
        "automation_type": "automated",
        "preconditions": [
          "目标环境可用",
          "TestTool 已完成用户绑定"
        ],
        "steps": [
          {
            "id": "69be7cbf-58be-42f2-a338-ecd73b059a03",
            "action": "执行 L2 阶段场景",
            "expected": "结果符合需求"
          }
        ],
        "status": "passed",
        "actual_result": "真实生成用例的 Mock 执行通过",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [
          {
            "level": "info",
            "message": "review execution passed"
          }
        ],
        "artifacts": [],
        "updated_at": "2026-09-14T06:53:00.158480Z"
      }
    },
    "logs": [
      {
        "level": "info",
        "message": "task completed"
      }
    ],
    "artifacts": [],
    "case_platform_url": "http://127.0.0.1:3000/playlists/b4101aa1-1607-471c-a0a8-a9a3d4c7388d",
    "lease_expires_at": "2026-09-14T06:57:58.066319Z"
  }
}
```

### 13. 幂等重放相同 update_id

耗时：22 ms

请求：

```json
{
  "method": "PATCH",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00025",
  "headers": {
    "Authorization": "Bearer ***",
    "X-TestTool-User-ID": "executor@casepilot.local"
  },
  "body": {
    "update_id": "b5dd1ff0-78a3-4400-8d05-8d3ec85f2cd2",
    "lease_token": "***",
    "status": "completed",
    "updated_at": "2026-09-14T06:53:00.158480+00:00",
    "cases_complete": true,
    "cases": {
      "CP-00040-CASE-001": {
        "status": "passed",
        "updated_at": "2026-09-14T06:53:00.158480+00:00",
        "actual_result": "真实生成用例的 Mock 执行通过",
        "completed_step_ids": [],
        "logs": [
          {
            "level": "info",
            "message": "review execution passed"
          }
        ],
        "artifacts": []
      },
      "CP-00040-CASE-002": {
        "status": "passed",
        "updated_at": "2026-09-14T06:53:00.158480+00:00",
        "actual_result": "真实生成用例的 Mock 执行通过",
        "completed_step_ids": [],
        "logs": [
          {
            "level": "info",
            "message": "review execution passed"
          }
        ],
        "artifacts": []
      }
    },
    "logs": [
      {
        "level": "info",
        "message": "task completed"
      }
    ],
    "artifacts": []
  }
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "test_task_id": "TASK-00025",
    "task_request_id": "20c9625a-4fd9-4888-a0d4-8f4768072c45",
    "case_project_id": "CP-00040",
    "case_generation_id": "CASE-SESSION-00071",
    "target_type": "fr_test",
    "target_id": 1368775591,
    "target_key": "FR-REVIEW-1368775591",
    "task_name": "FR-REVIEW-1368775591 execution",
    "tester": "executor@casepilot.local",
    "execution_notes": "执行 L2 累计范围并同步结果",
    "execution_level": "L2",
    "execution_status": "completed",
    "updated_at": "2026-09-14T06:53:00.158480Z",
    "cases_complete": true,
    "cases": {
      "CP-00040-CASE-001": {
        "case_id": "CP-00040-CASE-001",
        "title": "FR-REVIEW-1368775591：验证核心成功路径",
        "stage": "L0",
        "test_domain": [
          "Function"
        ],
        "automation_type": "manual",
        "preconditions": [
          "目标环境可用",
          "TestTool 已完成用户绑定"
        ],
        "steps": [
          {
            "id": "98e04091-e497-4917-afd6-d5fa5beb7587",
            "action": "执行 L0 阶段场景",
            "expected": "结果符合需求"
          }
        ],
        "status": "passed",
        "actual_result": "真实生成用例的 Mock 执行通过",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [
          {
            "level": "info",
            "message": "review execution passed"
          }
        ],
        "artifacts": [],
        "updated_at": "2026-09-14T06:53:00.158480Z"
      },
      "CP-00040-CASE-002": {
        "case_id": "CP-00040-CASE-002",
        "title": "FR-REVIEW-1368775591：验证异常输入与恢复路径",
        "stage": "L2",
        "test_domain": [
          "Reliability"
        ],
        "automation_type": "automated",
        "preconditions": [
          "目标环境可用",
          "TestTool 已完成用户绑定"
        ],
        "steps": [
          {
            "id": "69be7cbf-58be-42f2-a338-ecd73b059a03",
            "action": "执行 L2 阶段场景",
            "expected": "结果符合需求"
          }
        ],
        "status": "passed",
        "actual_result": "真实生成用例的 Mock 执行通过",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [
          {
            "level": "info",
            "message": "review execution passed"
          }
        ],
        "artifacts": [],
        "updated_at": "2026-09-14T06:53:00.158480Z"
      }
    },
    "logs": [
      {
        "level": "info",
        "message": "task completed"
      }
    ],
    "artifacts": [],
    "case_platform_url": "http://127.0.0.1:3000/playlists/b4101aa1-1607-471c-a0a8-a9a3d4c7388d",
    "lease_expires_at": "2026-09-14T06:57:58.066319Z"
  }
}
```

### 14. 查询单个任务用例

耗时：23 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00025/cases/CP-00040-CASE-001",
  "headers": {
    "Authorization": "Bearer ***",
    "X-TestTool-User-ID": "executor@casepilot.local"
  },
  "body": null
}
```

返回：

```json
{
  "status": 200,
  "headers": {
    "content-type": "application/json"
  },
  "body": {
    "case_id": "CP-00040-CASE-001",
    "title": "FR-REVIEW-1368775591：验证核心成功路径",
    "stage": "L0",
    "test_domain": [
      "Function"
    ],
    "automation_type": "manual",
    "preconditions": [
      "目标环境可用",
      "TestTool 已完成用户绑定"
    ],
    "steps": [
      {
        "id": "98e04091-e497-4917-afd6-d5fa5beb7587",
        "action": "执行 L0 阶段场景",
        "expected": "结果符合需求"
      }
    ],
    "status": "passed",
    "actual_result": "真实生成用例的 Mock 执行通过",
    "completed_step_ids": [],
    "defect_ref": "",
    "logs": [
      {
        "level": "info",
        "message": "review execution passed"
      }
    ],
    "artifacts": [],
    "updated_at": "2026-09-14T06:53:00.158480Z"
  }
}
```

## 异步状态回调

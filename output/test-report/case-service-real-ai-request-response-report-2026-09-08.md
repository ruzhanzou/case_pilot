# Case Service 接口逐请求测试报告

- 执行时间：2026-09-07T17:31:21.813133+00:00
- 生成模式：real
- 结果：PASSED
- Case Project：CP-00009
- Generation：CASE-SESSION-00012
- Task：TASK-00008
- 客户端请求数：93
- 异步回调数：12

## 客户端请求与返回

### 1. 创建空用例集合

耗时：21 ms

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
      "target_id": 802281907,
      "target_key": "FR-REVIEW-802281907",
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
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009"
  }
}
```

### 2. 启动异步用例生成

耗时：19 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-generation-jobs",
  "headers": {
    "Authorization": "Bearer ***"
  },
  "body": {
    "test_target": {
      "target_type": "fr_test",
      "target_id": 802281907,
      "target_key": "FR-REVIEW-802281907",
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
    "case_generation_id": "CASE-SESSION-00012",
    "case_generation_status": "generating",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009"
  }
}
```

### 3. 轮询生成状态 #1

耗时：14 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:21.938699Z",
    "cases": {}
  }
}
```

### 4. 轮询生成状态 #2

耗时：12 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 5. 轮询生成状态 #3

耗时：15 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 6. 轮询生成状态 #4

耗时：22 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 7. 轮询生成状态 #5

耗时：24 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 8. 轮询生成状态 #6

耗时：30 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 9. 轮询生成状态 #7

耗时：22 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 10. 轮询生成状态 #8

耗时：26 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 11. 轮询生成状态 #9

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 12. 轮询生成状态 #10

耗时：27 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 13. 轮询生成状态 #11

耗时：22 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 14. 轮询生成状态 #12

耗时：21 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 15. 轮询生成状态 #13

耗时：23 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 16. 轮询生成状态 #14

耗时：24 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:22.626888Z",
    "cases": {}
  }
}
```

### 17. 轮询生成状态 #15

耗时：21 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 18. 轮询生成状态 #16

耗时：23 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 19. 轮询生成状态 #17

耗时：22 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 20. 轮询生成状态 #18

耗时：24 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 21. 轮询生成状态 #19

耗时：20 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 22. 轮询生成状态 #20

耗时：23 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 23. 轮询生成状态 #21

耗时：24 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 24. 轮询生成状态 #22

耗时：16 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 25. 轮询生成状态 #23

耗时：20 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 26. 轮询生成状态 #24

耗时：26 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 27. 轮询生成状态 #25

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 28. 轮询生成状态 #26

耗时：26 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 29. 轮询生成状态 #27

耗时：23 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 30. 轮询生成状态 #28

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:31:49.565612Z",
    "cases": {}
  }
}
```

### 31. 轮询生成状态 #29

耗时：22 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 32. 轮询生成状态 #30

耗时：24 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 33. 轮询生成状态 #31

耗时：27 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 34. 轮询生成状态 #32

耗时：26 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 35. 轮询生成状态 #33

耗时：27 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 36. 轮询生成状态 #34

耗时：27 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 37. 轮询生成状态 #35

耗时：22 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 38. 轮询生成状态 #36

耗时：22 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 39. 轮询生成状态 #37

耗时：13 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 40. 轮询生成状态 #38

耗时：16 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 41. 轮询生成状态 #39

耗时：19 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 42. 轮询生成状态 #40

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 43. 轮询生成状态 #41

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 44. 轮询生成状态 #42

耗时：20 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 45. 轮询生成状态 #43

耗时：14 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 46. 轮询生成状态 #44

耗时：20 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 47. 轮询生成状态 #45

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 48. 轮询生成状态 #46

耗时：18 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 49. 轮询生成状态 #47

耗时：43 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 50. 轮询生成状态 #48

耗时：18 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:18.258437Z",
    "cases": {}
  }
}
```

### 51. 轮询生成状态 #49

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 52. 轮询生成状态 #50

耗时：13 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 53. 轮询生成状态 #51

耗时：12 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 54. 轮询生成状态 #52

耗时：24 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 55. 轮询生成状态 #53

耗时：16 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 56. 轮询生成状态 #54

耗时：23 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 57. 轮询生成状态 #55

耗时：23 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 58. 轮询生成状态 #56

耗时：17 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 59. 轮询生成状态 #57

耗时：12 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 60. 轮询生成状态 #58

耗时：24 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 61. 轮询生成状态 #59

耗时：27 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 62. 轮询生成状态 #60

耗时：23 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 63. 轮询生成状态 #61

耗时：12 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 64. 轮询生成状态 #62

耗时：10 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 65. 轮询生成状态 #63

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 66. 轮询生成状态 #64

耗时：26 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 67. 轮询生成状态 #65

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 68. 轮询生成状态 #66

耗时：11 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 69. 轮询生成状态 #67

耗时：13 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 70. 轮询生成状态 #68

耗时：22 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 71. 轮询生成状态 #69

耗时：26 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 72. 轮询生成状态 #70

耗时：11 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 73. 轮询生成状态 #71

耗时：14 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 74. 轮询生成状态 #72

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 75. 轮询生成状态 #73

耗时：28 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 76. 轮询生成状态 #74

耗时：22 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 77. 轮询生成状态 #75

耗时：24 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 78. 轮询生成状态 #76

耗时：17 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 79. 轮询生成状态 #77

耗时：24 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 80. 轮询生成状态 #78

耗时：26 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 81. 轮询生成状态 #79

耗时：21 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 82. 轮询生成状态 #80

耗时：25 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "generating",
    "generation_updated_at": "2026-09-07T17:32:58.594279Z",
    "cases": {}
  }
}
```

### 83. 轮询生成状态 #81

耗时：16 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "approved",
    "generation_updated_at": "2026-09-07T17:34:02.457869Z",
    "cases": {
      "CP-00009-CASE-001": {
        "stage": "L0",
        "test_domain": [
          "功能测试",
          "音频说话人分离模块"
        ],
        "title": "正常网络环境下设备所有者说话人分离识别验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-002": {
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "title": "离线网络环境下设备所有者说话人分离功能验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-003": {
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "title": "高抖动弱网环境下设备所有者说话人分离功能验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-004": {
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "title": "离线网络恢复正常后设备所有者说话人分离功能自动恢复验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-005": {
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "title": "高抖动弱网恢复正常后设备所有者说话人分离功能自动恢复验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-006": {
        "stage": "L4",
        "test_domain": [
          "稳定性测试",
          "音频说话人分离模块"
        ],
        "title": "设备所有者说话人分离功能连续运行1小时稳定性验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-007": {
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "title": "离线网络环境下多次触发设备所有者说话人分离功能验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-008": {
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "title": "高抖动弱网环境下多次触发设备所有者说话人分离功能验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-009": {
        "stage": "L4",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "title": "多次在离线和正常网络间切换后功能恢复验证",
        "automation_type": "manual"
      }
    }
  }
}
```

### 84. POST 方式读取完整用例快照

耗时：15 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/case-summary",
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
    "target_id": 802281907,
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_status": "approved",
    "generation_updated_at": "2026-09-07T17:34:02.457869Z",
    "cases": {
      "CP-00009-CASE-001": {
        "stage": "L0",
        "test_domain": [
          "功能测试",
          "音频说话人分离模块"
        ],
        "title": "正常网络环境下设备所有者说话人分离识别验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-002": {
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "title": "离线网络环境下设备所有者说话人分离功能验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-003": {
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "title": "高抖动弱网环境下设备所有者说话人分离功能验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-004": {
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "title": "离线网络恢复正常后设备所有者说话人分离功能自动恢复验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-005": {
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "title": "高抖动弱网恢复正常后设备所有者说话人分离功能自动恢复验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-006": {
        "stage": "L4",
        "test_domain": [
          "稳定性测试",
          "音频说话人分离模块"
        ],
        "title": "设备所有者说话人分离功能连续运行1小时稳定性验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-007": {
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "title": "离线网络环境下多次触发设备所有者说话人分离功能验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-008": {
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "title": "高抖动弱网环境下多次触发设备所有者说话人分离功能验证",
        "automation_type": "manual"
      },
      "CP-00009-CASE-009": {
        "stage": "L4",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "title": "多次在离线和正常网络间切换后功能恢复验证",
        "automation_type": "manual"
      }
    }
  }
}
```

### 85. 创建待确认执行任务

耗时：47 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/case-projects/CP-00009/tasks",
  "headers": {
    "Authorization": "Bearer ***"
  },
  "body": {
    "test_target": {
      "target_type": "fr_test",
      "target_id": 802281907,
      "target_key": "FR-REVIEW-802281907",
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
    "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4",
    "case_generation_id": "CASE-SESSION-00012"
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
    "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4",
    "test_task_id": "TASK-00008",
    "execution_status": "pending_confirmation",
    "case_platform_url": "http://127.0.0.1:3000/playlists/c5a052db-e3d7-46d5-a62a-87589d04e60e?task_request_id=8be5a0e9-4a07-402a-949c-83852147eac4&case_project_id=CP-00009"
  }
}
```

### 86. 登录 CasePilot 确认人

耗时：95 ms

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

### 87. 确认 Playlist 并冻结 ExecutionRun

耗时：127 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/api/v1/integration-task-requests/8be5a0e9-4a07-402a-949c-83852147eac4/confirm",
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
    "test_task_id": "TASK-00008",
    "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4",
    "case_project_id": "CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "target_type": "fr_test",
    "target_id": 802281907,
    "target_key": "FR-REVIEW-802281907",
    "task_name": "FR-REVIEW-802281907 execution",
    "tester": "executor@casepilot.local",
    "execution_notes": "执行 L2 累计范围并同步结果",
    "execution_level": "L2",
    "execution_status": "confirmed",
    "updated_at": "2026-09-07T17:34:04.586957Z",
    "cases_complete": true,
    "cases": {
      "CP-00009-CASE-001": {
        "case_id": "CP-00009-CASE-001",
        "title": "正常网络环境下设备所有者说话人分离识别验证",
        "stage": "L0",
        "test_domain": [
          "功能测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络为正常网络",
          "已录入设备所有者语音样本",
          "测试验证工具准备完成"
        ],
        "steps": [
          {
            "id": "b0ce19bd-8744-4fc8-8e22-fc88bd5b4369",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常启动，能够正常采集音频数据"
          },
          {
            "id": "c38313f6-8ff9-4143-b518-ca9f7d4f81e9",
            "action": "查看分离识别结果输出",
            "expected": "设备所有者语音被正确分离识别，符合功能要求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535617Z"
      },
      "CP-00009-CASE-002": {
        "case_id": "CP-00009-CASE-002",
        "title": "离线网络环境下设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为offline离线状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "ecca51fd-5341-4cfa-8aad-2d12d84bd5da",
            "action": "触发设备所有者说话人分离功能，设备所有者开始说话",
            "expected": "应用无崩溃、无响应，按照预期离线逻辑处理请求"
          },
          {
            "id": "1fd5fcd0-51f8-4626-83d3-1ddfe79377eb",
            "action": "检查应用状态和功能输出",
            "expected": "无未处理异常抛出，功能处理符合预期离线逻辑"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535628Z"
      },
      "CP-00009-CASE-003": {
        "case_id": "CP-00009-CASE-003",
        "title": "高抖动弱网环境下设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "7d240c23-29c2-4545-9171-e1c15c77d896",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常启动，应用无崩溃无异常"
          },
          {
            "id": "a5ca2123-c549-49d3-9019-b7118e5f47cc",
            "action": "查看分离识别结果",
            "expected": "设备说话人分离识别准确率符合预期要求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535633Z"
      },
      "CP-00009-CASE-004": {
        "case_id": "CP-00009-CASE-004",
        "title": "离线网络恢复正常后设备所有者说话人分离功能自动恢复验证",
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络已先设置为离线状态，功能已触发运行",
          "已准备将网络恢复为正常状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "4fbd1495-7d8b-429e-a276-313306c1b2b9",
            "action": "将设备网络从离线恢复为正常网络，等待应用自动适配网络",
            "expected": "应用自动检测到网络恢复，无需手动重启功能"
          },
          {
            "id": "d735d4f2-fb58-4a4d-a5f7-4c7d89c19147",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535638Z"
      },
      "CP-00009-CASE-005": {
        "case_id": "CP-00009-CASE-005",
        "title": "高抖动弱网恢复正常后设备所有者说话人分离功能自动恢复验证",
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络已先设置为高抖动弱网状态，功能已触发运行",
          "已准备将网络恢复为正常状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "314b7d81-8fc8-424b-9b8c-d9123650cb75",
            "action": "将设备网络从高抖动弱网恢复为正常网络，等待应用自动适配网络",
            "expected": "应用自动检测到网络恢复，无需手动重启功能"
          },
          {
            "id": "5acb48a1-678d-4ac7-84c1-c4cf0a7418af",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535645Z"
      },
      "CP-00009-CASE-007": {
        "case_id": "CP-00009-CASE-007",
        "title": "离线网络环境下多次触发设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为offline离线状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "fe91de42-4a1c-428a-8cdf-746d0cf085a6",
            "action": "连续10次触发设备所有者说话人分离功能，每次触发后关闭功能",
            "expected": "每次触发都能正常响应，应用无崩溃、无异常报错"
          },
          {
            "id": "1a49efa6-82b5-45ae-9d7f-2f8a1b97bd33",
            "action": "最后一次触发后检查应用内存状态",
            "expected": "应用仍正常运行，内存无异常增长"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535650Z"
      },
      "CP-00009-CASE-008": {
        "case_id": "CP-00009-CASE-008",
        "title": "高抖动弱网环境下多次触发设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "898d7967-5c35-4f33-9e22-b1e9b39ef39b",
            "action": "连续10次触发设备所有者说话人分离功能，每次触发后进行识别操作，然后关闭功能",
            "expected": "每次触发都能正常响应，应用无崩溃、无异常，识别结果每次都符合准确率要求"
          },
          {
            "id": "b3403298-174b-4116-831d-cb8d8a84afb7",
            "action": "检查连续触发后的应用内存状态",
            "expected": "内存无异常增长，无泄漏迹象"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535654Z"
      }
    },
    "logs": [],
    "artifacts": [],
    "case_platform_url": "http://127.0.0.1:3000/playlists/c5a052db-e3d7-46d5-a62a-87589d04e60e",
    "lease_expires_at": null
  }
}
```

### 88. 按当前用户、target_type 与 case_id 查询任务

耗时：23 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks?target_type=fr_test&case_id=CP-00009-CASE-001",
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
        "test_task_id": "TASK-00008",
        "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4",
        "case_project_id": "CP-00009",
        "case_generation_id": "CASE-SESSION-00012",
        "target_type": "fr_test",
        "target_id": 802281907,
        "target_key": "FR-REVIEW-802281907",
        "task_name": "FR-REVIEW-802281907 execution",
        "tester": "executor@casepilot.local",
        "execution_notes": "执行 L2 累计范围并同步结果",
        "execution_level": "L2",
        "execution_status": "confirmed",
        "updated_at": "2026-09-07T17:34:04.586957Z",
        "cases_complete": true,
        "cases": {
          "CP-00009-CASE-001": {
            "case_id": "CP-00009-CASE-001",
            "title": "正常网络环境下设备所有者说话人分离识别验证",
            "stage": "L0",
            "test_domain": [
              "功能测试",
              "音频说话人分离模块"
            ],
            "automation_type": "manual",
            "preconditions": [
              "待测Android应用版本为review-real-1，已正常安装启动",
              "设备网络为正常网络",
              "已录入设备所有者语音样本",
              "测试验证工具准备完成"
            ],
            "steps": [
              {
                "id": "b0ce19bd-8744-4fc8-8e22-fc88bd5b4369",
                "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
                "expected": "功能正常启动，能够正常采集音频数据"
              },
              {
                "id": "c38313f6-8ff9-4143-b518-ca9f7d4f81e9",
                "action": "查看分离识别结果输出",
                "expected": "设备所有者语音被正确分离识别，符合功能要求"
              }
            ],
            "status": "not_run",
            "actual_result": "",
            "completed_step_ids": [],
            "defect_ref": "",
            "logs": [],
            "artifacts": [],
            "updated_at": "2026-09-07T17:34:04.535617Z"
          },
          "CP-00009-CASE-002": {
            "case_id": "CP-00009-CASE-002",
            "title": "离线网络环境下设备所有者说话人分离功能验证",
            "stage": "L2",
            "test_domain": [
              "异常场景测试",
              "音频说话人分离模块"
            ],
            "automation_type": "manual",
            "preconditions": [
              "待测Android应用版本为review-real-1，已正常安装启动",
              "测试工具已将设备网络模拟为offline离线状态",
              "已录入设备所有者语音样本"
            ],
            "steps": [
              {
                "id": "ecca51fd-5341-4cfa-8aad-2d12d84bd5da",
                "action": "触发设备所有者说话人分离功能，设备所有者开始说话",
                "expected": "应用无崩溃、无响应，按照预期离线逻辑处理请求"
              },
              {
                "id": "1fd5fcd0-51f8-4626-83d3-1ddfe79377eb",
                "action": "检查应用状态和功能输出",
                "expected": "无未处理异常抛出，功能处理符合预期离线逻辑"
              }
            ],
            "status": "not_run",
            "actual_result": "",
            "completed_step_ids": [],
            "defect_ref": "",
            "logs": [],
            "artifacts": [],
            "updated_at": "2026-09-07T17:34:04.535628Z"
          },
          "CP-00009-CASE-003": {
            "case_id": "CP-00009-CASE-003",
            "title": "高抖动弱网环境下设备所有者说话人分离功能验证",
            "stage": "L2",
            "test_domain": [
              "异常场景测试",
              "音频说话人分离模块"
            ],
            "automation_type": "manual",
            "preconditions": [
              "待测Android应用版本为review-real-1，已正常安装启动",
              "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
              "已录入设备所有者语音样本"
            ],
            "steps": [
              {
                "id": "7d240c23-29c2-4545-9171-e1c15c77d896",
                "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
                "expected": "功能正常启动，应用无崩溃无异常"
              },
              {
                "id": "a5ca2123-c549-49d3-9019-b7118e5f47cc",
                "action": "查看分离识别结果",
                "expected": "设备说话人分离识别准确率符合预期要求"
              }
            ],
            "status": "not_run",
            "actual_result": "",
            "completed_step_ids": [],
            "defect_ref": "",
            "logs": [],
            "artifacts": [],
            "updated_at": "2026-09-07T17:34:04.535633Z"
          },
          "CP-00009-CASE-004": {
            "case_id": "CP-00009-CASE-004",
            "title": "离线网络恢复正常后设备所有者说话人分离功能自动恢复验证",
            "stage": "L2",
            "test_domain": [
              "异常恢复测试",
              "音频说话人分离模块"
            ],
            "automation_type": "manual",
            "preconditions": [
              "待测Android应用版本为review-real-1，已正常安装启动",
              "设备网络已先设置为离线状态，功能已触发运行",
              "已准备将网络恢复为正常状态",
              "已录入设备所有者语音样本"
            ],
            "steps": [
              {
                "id": "4fbd1495-7d8b-429e-a276-313306c1b2b9",
                "action": "将设备网络从离线恢复为正常网络，等待应用自动适配网络",
                "expected": "应用自动检测到网络恢复，无需手动重启功能"
              },
              {
                "id": "d735d4f2-fb58-4a4d-a5f7-4c7d89c19147",
                "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
                "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
              }
            ],
            "status": "not_run",
            "actual_result": "",
            "completed_step_ids": [],
            "defect_ref": "",
            "logs": [],
            "artifacts": [],
            "updated_at": "2026-09-07T17:34:04.535638Z"
          },
          "CP-00009-CASE-005": {
            "case_id": "CP-00009-CASE-005",
            "title": "高抖动弱网恢复正常后设备所有者说话人分离功能自动恢复验证",
            "stage": "L2",
            "test_domain": [
              "异常恢复测试",
              "音频说话人分离模块"
            ],
            "automation_type": "manual",
            "preconditions": [
              "待测Android应用版本为review-real-1，已正常安装启动",
              "设备网络已先设置为高抖动弱网状态，功能已触发运行",
              "已准备将网络恢复为正常状态",
              "已录入设备所有者语音样本"
            ],
            "steps": [
              {
                "id": "314b7d81-8fc8-424b-9b8c-d9123650cb75",
                "action": "将设备网络从高抖动弱网恢复为正常网络，等待应用自动适配网络",
                "expected": "应用自动检测到网络恢复，无需手动重启功能"
              },
              {
                "id": "5acb48a1-678d-4ac7-84c1-c4cf0a7418af",
                "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
                "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
              }
            ],
            "status": "not_run",
            "actual_result": "",
            "completed_step_ids": [],
            "defect_ref": "",
            "logs": [],
            "artifacts": [],
            "updated_at": "2026-09-07T17:34:04.535645Z"
          },
          "CP-00009-CASE-007": {
            "case_id": "CP-00009-CASE-007",
            "title": "离线网络环境下多次触发设备所有者说话人分离功能验证",
            "stage": "L2",
            "test_domain": [
              "异常场景测试",
              "音频说话人分离模块"
            ],
            "automation_type": "manual",
            "preconditions": [
              "待测Android应用版本为review-real-1，已正常安装启动",
              "测试工具已将设备网络模拟为offline离线状态",
              "已录入设备所有者语音样本"
            ],
            "steps": [
              {
                "id": "fe91de42-4a1c-428a-8cdf-746d0cf085a6",
                "action": "连续10次触发设备所有者说话人分离功能，每次触发后关闭功能",
                "expected": "每次触发都能正常响应，应用无崩溃、无异常报错"
              },
              {
                "id": "1a49efa6-82b5-45ae-9d7f-2f8a1b97bd33",
                "action": "最后一次触发后检查应用内存状态",
                "expected": "应用仍正常运行，内存无异常增长"
              }
            ],
            "status": "not_run",
            "actual_result": "",
            "completed_step_ids": [],
            "defect_ref": "",
            "logs": [],
            "artifacts": [],
            "updated_at": "2026-09-07T17:34:04.535650Z"
          },
          "CP-00009-CASE-008": {
            "case_id": "CP-00009-CASE-008",
            "title": "高抖动弱网环境下多次触发设备所有者说话人分离功能验证",
            "stage": "L2",
            "test_domain": [
              "异常场景测试",
              "音频说话人分离模块"
            ],
            "automation_type": "manual",
            "preconditions": [
              "待测Android应用版本为review-real-1，已正常安装启动",
              "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
              "已录入设备所有者语音样本"
            ],
            "steps": [
              {
                "id": "898d7967-5c35-4f33-9e22-b1e9b39ef39b",
                "action": "连续10次触发设备所有者说话人分离功能，每次触发后进行识别操作，然后关闭功能",
                "expected": "每次触发都能正常响应，应用无崩溃、无异常，识别结果每次都符合准确率要求"
              },
              {
                "id": "b3403298-174b-4116-831d-cb8d8a84afb7",
                "action": "检查连续触发后的应用内存状态",
                "expected": "内存无异常增长，无泄漏迹象"
              }
            ],
            "status": "not_run",
            "actual_result": "",
            "completed_step_ids": [],
            "defect_ref": "",
            "logs": [],
            "artifacts": [],
            "updated_at": "2026-09-07T17:34:04.535654Z"
          }
        },
        "logs": [],
        "artifacts": [],
        "case_platform_url": "http://127.0.0.1:3000/playlists/c5a052db-e3d7-46d5-a62a-87589d04e60e",
        "lease_expires_at": null
      }
    ],
    "next_cursor": null
  }
}
```

### 89. TestTool 领取指定任务

耗时：29 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00008/claim",
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
    "test_task_id": "TASK-00008",
    "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4",
    "case_project_id": "CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "target_type": "fr_test",
    "target_id": 802281907,
    "target_key": "FR-REVIEW-802281907",
    "task_name": "FR-REVIEW-802281907 execution",
    "tester": "executor@casepilot.local",
    "execution_notes": "执行 L2 累计范围并同步结果",
    "execution_level": "L2",
    "execution_status": "running",
    "updated_at": "2026-09-07T17:34:04.636593Z",
    "cases_complete": true,
    "cases": {
      "CP-00009-CASE-001": {
        "case_id": "CP-00009-CASE-001",
        "title": "正常网络环境下设备所有者说话人分离识别验证",
        "stage": "L0",
        "test_domain": [
          "功能测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络为正常网络",
          "已录入设备所有者语音样本",
          "测试验证工具准备完成"
        ],
        "steps": [
          {
            "id": "b0ce19bd-8744-4fc8-8e22-fc88bd5b4369",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常启动，能够正常采集音频数据"
          },
          {
            "id": "c38313f6-8ff9-4143-b518-ca9f7d4f81e9",
            "action": "查看分离识别结果输出",
            "expected": "设备所有者语音被正确分离识别，符合功能要求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535617Z"
      },
      "CP-00009-CASE-002": {
        "case_id": "CP-00009-CASE-002",
        "title": "离线网络环境下设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为offline离线状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "ecca51fd-5341-4cfa-8aad-2d12d84bd5da",
            "action": "触发设备所有者说话人分离功能，设备所有者开始说话",
            "expected": "应用无崩溃、无响应，按照预期离线逻辑处理请求"
          },
          {
            "id": "1fd5fcd0-51f8-4626-83d3-1ddfe79377eb",
            "action": "检查应用状态和功能输出",
            "expected": "无未处理异常抛出，功能处理符合预期离线逻辑"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535628Z"
      },
      "CP-00009-CASE-003": {
        "case_id": "CP-00009-CASE-003",
        "title": "高抖动弱网环境下设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "7d240c23-29c2-4545-9171-e1c15c77d896",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常启动，应用无崩溃无异常"
          },
          {
            "id": "a5ca2123-c549-49d3-9019-b7118e5f47cc",
            "action": "查看分离识别结果",
            "expected": "设备说话人分离识别准确率符合预期要求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535633Z"
      },
      "CP-00009-CASE-004": {
        "case_id": "CP-00009-CASE-004",
        "title": "离线网络恢复正常后设备所有者说话人分离功能自动恢复验证",
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络已先设置为离线状态，功能已触发运行",
          "已准备将网络恢复为正常状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "4fbd1495-7d8b-429e-a276-313306c1b2b9",
            "action": "将设备网络从离线恢复为正常网络，等待应用自动适配网络",
            "expected": "应用自动检测到网络恢复，无需手动重启功能"
          },
          {
            "id": "d735d4f2-fb58-4a4d-a5f7-4c7d89c19147",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535638Z"
      },
      "CP-00009-CASE-005": {
        "case_id": "CP-00009-CASE-005",
        "title": "高抖动弱网恢复正常后设备所有者说话人分离功能自动恢复验证",
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络已先设置为高抖动弱网状态，功能已触发运行",
          "已准备将网络恢复为正常状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "314b7d81-8fc8-424b-9b8c-d9123650cb75",
            "action": "将设备网络从高抖动弱网恢复为正常网络，等待应用自动适配网络",
            "expected": "应用自动检测到网络恢复，无需手动重启功能"
          },
          {
            "id": "5acb48a1-678d-4ac7-84c1-c4cf0a7418af",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535645Z"
      },
      "CP-00009-CASE-007": {
        "case_id": "CP-00009-CASE-007",
        "title": "离线网络环境下多次触发设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为offline离线状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "fe91de42-4a1c-428a-8cdf-746d0cf085a6",
            "action": "连续10次触发设备所有者说话人分离功能，每次触发后关闭功能",
            "expected": "每次触发都能正常响应，应用无崩溃、无异常报错"
          },
          {
            "id": "1a49efa6-82b5-45ae-9d7f-2f8a1b97bd33",
            "action": "最后一次触发后检查应用内存状态",
            "expected": "应用仍正常运行，内存无异常增长"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535650Z"
      },
      "CP-00009-CASE-008": {
        "case_id": "CP-00009-CASE-008",
        "title": "高抖动弱网环境下多次触发设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "898d7967-5c35-4f33-9e22-b1e9b39ef39b",
            "action": "连续10次触发设备所有者说话人分离功能，每次触发后进行识别操作，然后关闭功能",
            "expected": "每次触发都能正常响应，应用无崩溃、无异常，识别结果每次都符合准确率要求"
          },
          {
            "id": "b3403298-174b-4116-831d-cb8d8a84afb7",
            "action": "检查连续触发后的应用内存状态",
            "expected": "内存无异常增长，无泄漏迹象"
          }
        ],
        "status": "not_run",
        "actual_result": "",
        "completed_step_ids": [],
        "defect_ref": "",
        "logs": [],
        "artifacts": [],
        "updated_at": "2026-09-07T17:34:04.535654Z"
      }
    },
    "logs": [],
    "artifacts": [],
    "case_platform_url": "http://127.0.0.1:3000/playlists/c5a052db-e3d7-46d5-a62a-87589d04e60e",
    "lease_expires_at": "2026-09-07T17:39:04.636593Z",
    "lease_token": "***"
  }
}
```

### 90. TestTool 续租

耗时：16 ms

请求：

```json
{
  "method": "POST",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00008/heartbeat",
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
    "test_task_id": "TASK-00008",
    "lease_expires_at": "2026-09-07T17:39:04.668332Z"
  }
}
```

### 91. 上报完整任务与用例状态

耗时：133 ms

请求：

```json
{
  "method": "PATCH",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00008",
  "headers": {
    "Authorization": "Bearer ***",
    "X-TestTool-User-ID": "executor@casepilot.local"
  },
  "body": {
    "update_id": "d01036ed-2fe8-4e2b-9059-126ae23d66f5",
    "lease_token": "***",
    "status": "completed",
    "updated_at": "2026-09-07T17:34:06.673753+00:00",
    "cases_complete": true,
    "cases": {
      "CP-00009-CASE-001": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-002": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-003": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-004": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-005": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-007": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-008": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
    "test_task_id": "TASK-00008",
    "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4",
    "case_project_id": "CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "target_type": "fr_test",
    "target_id": 802281907,
    "target_key": "FR-REVIEW-802281907",
    "task_name": "FR-REVIEW-802281907 execution",
    "tester": "executor@casepilot.local",
    "execution_notes": "执行 L2 累计范围并同步结果",
    "execution_level": "L2",
    "execution_status": "completed",
    "updated_at": "2026-09-07T17:34:06.673753Z",
    "cases_complete": true,
    "cases": {
      "CP-00009-CASE-001": {
        "case_id": "CP-00009-CASE-001",
        "title": "正常网络环境下设备所有者说话人分离识别验证",
        "stage": "L0",
        "test_domain": [
          "功能测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络为正常网络",
          "已录入设备所有者语音样本",
          "测试验证工具准备完成"
        ],
        "steps": [
          {
            "id": "b0ce19bd-8744-4fc8-8e22-fc88bd5b4369",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常启动，能够正常采集音频数据"
          },
          {
            "id": "c38313f6-8ff9-4143-b518-ca9f7d4f81e9",
            "action": "查看分离识别结果输出",
            "expected": "设备所有者语音被正确分离识别，符合功能要求"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-002": {
        "case_id": "CP-00009-CASE-002",
        "title": "离线网络环境下设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为offline离线状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "ecca51fd-5341-4cfa-8aad-2d12d84bd5da",
            "action": "触发设备所有者说话人分离功能，设备所有者开始说话",
            "expected": "应用无崩溃、无响应，按照预期离线逻辑处理请求"
          },
          {
            "id": "1fd5fcd0-51f8-4626-83d3-1ddfe79377eb",
            "action": "检查应用状态和功能输出",
            "expected": "无未处理异常抛出，功能处理符合预期离线逻辑"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-003": {
        "case_id": "CP-00009-CASE-003",
        "title": "高抖动弱网环境下设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "7d240c23-29c2-4545-9171-e1c15c77d896",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常启动，应用无崩溃无异常"
          },
          {
            "id": "a5ca2123-c549-49d3-9019-b7118e5f47cc",
            "action": "查看分离识别结果",
            "expected": "设备说话人分离识别准确率符合预期要求"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-004": {
        "case_id": "CP-00009-CASE-004",
        "title": "离线网络恢复正常后设备所有者说话人分离功能自动恢复验证",
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络已先设置为离线状态，功能已触发运行",
          "已准备将网络恢复为正常状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "4fbd1495-7d8b-429e-a276-313306c1b2b9",
            "action": "将设备网络从离线恢复为正常网络，等待应用自动适配网络",
            "expected": "应用自动检测到网络恢复，无需手动重启功能"
          },
          {
            "id": "d735d4f2-fb58-4a4d-a5f7-4c7d89c19147",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-005": {
        "case_id": "CP-00009-CASE-005",
        "title": "高抖动弱网恢复正常后设备所有者说话人分离功能自动恢复验证",
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络已先设置为高抖动弱网状态，功能已触发运行",
          "已准备将网络恢复为正常状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "314b7d81-8fc8-424b-9b8c-d9123650cb75",
            "action": "将设备网络从高抖动弱网恢复为正常网络，等待应用自动适配网络",
            "expected": "应用自动检测到网络恢复，无需手动重启功能"
          },
          {
            "id": "5acb48a1-678d-4ac7-84c1-c4cf0a7418af",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-007": {
        "case_id": "CP-00009-CASE-007",
        "title": "离线网络环境下多次触发设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为offline离线状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "fe91de42-4a1c-428a-8cdf-746d0cf085a6",
            "action": "连续10次触发设备所有者说话人分离功能，每次触发后关闭功能",
            "expected": "每次触发都能正常响应，应用无崩溃、无异常报错"
          },
          {
            "id": "1a49efa6-82b5-45ae-9d7f-2f8a1b97bd33",
            "action": "最后一次触发后检查应用内存状态",
            "expected": "应用仍正常运行，内存无异常增长"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-008": {
        "case_id": "CP-00009-CASE-008",
        "title": "高抖动弱网环境下多次触发设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "898d7967-5c35-4f33-9e22-b1e9b39ef39b",
            "action": "连续10次触发设备所有者说话人分离功能，每次触发后进行识别操作，然后关闭功能",
            "expected": "每次触发都能正常响应，应用无崩溃、无异常，识别结果每次都符合准确率要求"
          },
          {
            "id": "b3403298-174b-4116-831d-cb8d8a84afb7",
            "action": "检查连续触发后的应用内存状态",
            "expected": "内存无异常增长，无泄漏迹象"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      }
    },
    "logs": [
      {
        "level": "info",
        "message": "task completed"
      }
    ],
    "artifacts": [],
    "case_platform_url": "http://127.0.0.1:3000/playlists/c5a052db-e3d7-46d5-a62a-87589d04e60e",
    "lease_expires_at": "2026-09-07T17:39:04.668332Z"
  }
}
```

### 92. 幂等重放相同 update_id

耗时：11 ms

请求：

```json
{
  "method": "PATCH",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00008",
  "headers": {
    "Authorization": "Bearer ***",
    "X-TestTool-User-ID": "executor@casepilot.local"
  },
  "body": {
    "update_id": "d01036ed-2fe8-4e2b-9059-126ae23d66f5",
    "lease_token": "***",
    "status": "completed",
    "updated_at": "2026-09-07T17:34:06.673753+00:00",
    "cases_complete": true,
    "cases": {
      "CP-00009-CASE-001": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-002": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-003": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-004": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-005": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-007": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
      "CP-00009-CASE-008": {
        "status": "passed",
        "updated_at": "2026-09-07T17:34:06.673753+00:00",
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
    "test_task_id": "TASK-00008",
    "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4",
    "case_project_id": "CP-00009",
    "case_generation_id": "CASE-SESSION-00012",
    "target_type": "fr_test",
    "target_id": 802281907,
    "target_key": "FR-REVIEW-802281907",
    "task_name": "FR-REVIEW-802281907 execution",
    "tester": "executor@casepilot.local",
    "execution_notes": "执行 L2 累计范围并同步结果",
    "execution_level": "L2",
    "execution_status": "completed",
    "updated_at": "2026-09-07T17:34:06.673753Z",
    "cases_complete": true,
    "cases": {
      "CP-00009-CASE-001": {
        "case_id": "CP-00009-CASE-001",
        "title": "正常网络环境下设备所有者说话人分离识别验证",
        "stage": "L0",
        "test_domain": [
          "功能测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络为正常网络",
          "已录入设备所有者语音样本",
          "测试验证工具准备完成"
        ],
        "steps": [
          {
            "id": "b0ce19bd-8744-4fc8-8e22-fc88bd5b4369",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常启动，能够正常采集音频数据"
          },
          {
            "id": "c38313f6-8ff9-4143-b518-ca9f7d4f81e9",
            "action": "查看分离识别结果输出",
            "expected": "设备所有者语音被正确分离识别，符合功能要求"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-002": {
        "case_id": "CP-00009-CASE-002",
        "title": "离线网络环境下设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为offline离线状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "ecca51fd-5341-4cfa-8aad-2d12d84bd5da",
            "action": "触发设备所有者说话人分离功能，设备所有者开始说话",
            "expected": "应用无崩溃、无响应，按照预期离线逻辑处理请求"
          },
          {
            "id": "1fd5fcd0-51f8-4626-83d3-1ddfe79377eb",
            "action": "检查应用状态和功能输出",
            "expected": "无未处理异常抛出，功能处理符合预期离线逻辑"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-003": {
        "case_id": "CP-00009-CASE-003",
        "title": "高抖动弱网环境下设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "7d240c23-29c2-4545-9171-e1c15c77d896",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常启动，应用无崩溃无异常"
          },
          {
            "id": "a5ca2123-c549-49d3-9019-b7118e5f47cc",
            "action": "查看分离识别结果",
            "expected": "设备说话人分离识别准确率符合预期要求"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-004": {
        "case_id": "CP-00009-CASE-004",
        "title": "离线网络恢复正常后设备所有者说话人分离功能自动恢复验证",
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络已先设置为离线状态，功能已触发运行",
          "已准备将网络恢复为正常状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "4fbd1495-7d8b-429e-a276-313306c1b2b9",
            "action": "将设备网络从离线恢复为正常网络，等待应用自动适配网络",
            "expected": "应用自动检测到网络恢复，无需手动重启功能"
          },
          {
            "id": "d735d4f2-fb58-4a4d-a5f7-4c7d89c19147",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-005": {
        "case_id": "CP-00009-CASE-005",
        "title": "高抖动弱网恢复正常后设备所有者说话人分离功能自动恢复验证",
        "stage": "L2",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "设备网络已先设置为高抖动弱网状态，功能已触发运行",
          "已准备将网络恢复为正常状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "314b7d81-8fc8-424b-9b8c-d9123650cb75",
            "action": "将设备网络从高抖动弱网恢复为正常网络，等待应用自动适配网络",
            "expected": "应用自动检测到网络恢复，无需手动重启功能"
          },
          {
            "id": "5acb48a1-678d-4ac7-84c1-c4cf0a7418af",
            "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
            "expected": "功能正常运行，能够正确分离识别设备所有者语音，结果符合要求"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-007": {
        "case_id": "CP-00009-CASE-007",
        "title": "离线网络环境下多次触发设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为offline离线状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "fe91de42-4a1c-428a-8cdf-746d0cf085a6",
            "action": "连续10次触发设备所有者说话人分离功能，每次触发后关闭功能",
            "expected": "每次触发都能正常响应，应用无崩溃、无异常报错"
          },
          {
            "id": "1a49efa6-82b5-45ae-9d7f-2f8a1b97bd33",
            "action": "最后一次触发后检查应用内存状态",
            "expected": "应用仍正常运行，内存无异常增长"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      },
      "CP-00009-CASE-008": {
        "case_id": "CP-00009-CASE-008",
        "title": "高抖动弱网环境下多次触发设备所有者说话人分离功能验证",
        "stage": "L2",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual",
        "preconditions": [
          "待测Android应用版本为review-real-1，已正常安装启动",
          "测试工具已将设备网络模拟为high_jitter高抖动弱网状态",
          "已录入设备所有者语音样本"
        ],
        "steps": [
          {
            "id": "898d7967-5c35-4f33-9e22-b1e9b39ef39b",
            "action": "连续10次触发设备所有者说话人分离功能，每次触发后进行识别操作，然后关闭功能",
            "expected": "每次触发都能正常响应，应用无崩溃、无异常，识别结果每次都符合准确率要求"
          },
          {
            "id": "b3403298-174b-4116-831d-cb8d8a84afb7",
            "action": "检查连续触发后的应用内存状态",
            "expected": "内存无异常增长，无泄漏迹象"
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
        "updated_at": "2026-09-07T17:34:06.673753Z"
      }
    },
    "logs": [
      {
        "level": "info",
        "message": "task completed"
      }
    ],
    "artifacts": [],
    "case_platform_url": "http://127.0.0.1:3000/playlists/c5a052db-e3d7-46d5-a62a-87589d04e60e",
    "lease_expires_at": "2026-09-07T17:39:04.668332Z"
  }
}
```

### 93. 查询单个任务用例

耗时：13 ms

请求：

```json
{
  "method": "GET",
  "path": "http://127.0.0.1:8000/api/test-tool/v1/tasks/TASK-00008/cases/CP-00009-CASE-001",
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
    "case_id": "CP-00009-CASE-001",
    "title": "正常网络环境下设备所有者说话人分离识别验证",
    "stage": "L0",
    "test_domain": [
      "功能测试",
      "音频说话人分离模块"
    ],
    "automation_type": "manual",
    "preconditions": [
      "待测Android应用版本为review-real-1，已正常安装启动",
      "设备网络为正常网络",
      "已录入设备所有者语音样本",
      "测试验证工具准备完成"
    ],
    "steps": [
      {
        "id": "b0ce19bd-8744-4fc8-8e22-fc88bd5b4369",
        "action": "触发设备所有者说话人分离功能，设备所有者和非所有者同时说话",
        "expected": "功能正常启动，能够正常采集音频数据"
      },
      {
        "id": "c38313f6-8ff9-4143-b518-ca9f7d4f81e9",
        "action": "查看分离识别结果输出",
        "expected": "设备所有者语音被正确分离识别，符合功能要求"
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
    "updated_at": "2026-09-07T17:34:06.673753Z"
  }
}
```

## 异步状态回调

### Callback 1: /api/case-service/callbacks/generation-status

```json
{
  "received_at": "2026-09-07T17:31:23.459460+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/generation-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "26d6984f-71b9-402d-b5b0-ef0857eb6d9a",
    "Content-Length": "277"
  },
  "body": {
    "target_id": 802281907,
    "target_type": "fr_test",
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "generation_status": "generating",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_updated_at": "2026-09-07T17:31:21.938699+00:00"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 2: /api/case-service/callbacks/generation-status

```json
{
  "received_at": "2026-09-07T17:31:23.473032+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/generation-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "e5808cf5-ddab-48bd-b251-c03dc9f44dec",
    "Content-Length": "340"
  },
  "body": {
    "target_id": 802281907,
    "target_type": "fr_test",
    "case_project_id": "CP-00009",
    "generation_stage": "context.prepared",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "generation_status": "generating",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_progress": 10,
    "generation_updated_at": "2026-09-07T17:31:22.626888+00:00"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 3: /api/case-service/callbacks/generation-status

```json
{
  "received_at": "2026-09-07T17:31:51.462081+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/generation-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "fd997f90-51c9-4e3f-80cc-4961f72f4f38",
    "Content-Length": "344"
  },
  "body": {
    "target_id": 802281907,
    "target_type": "fr_test",
    "case_project_id": "CP-00009",
    "generation_stage": "requirement.analyzed",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "generation_status": "generating",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_progress": 22,
    "generation_updated_at": "2026-09-07T17:31:49.565612+00:00"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 4: /api/case-service/callbacks/generation-status

```json
{
  "received_at": "2026-09-07T17:32:19.468175+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/generation-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "ae1fc1ac-a6c2-4308-b649-c357d55a15f1",
    "Content-Length": "341"
  },
  "body": {
    "target_id": 802281907,
    "target_type": "fr_test",
    "case_project_id": "CP-00009",
    "generation_stage": "feature.generated",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "generation_status": "generating",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_progress": 38,
    "generation_updated_at": "2026-09-07T17:32:18.258437+00:00"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 5: /api/case-service/callbacks/generation-status

```json
{
  "received_at": "2026-09-07T17:32:59.463007+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/generation-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "c8293bc2-0965-4be5-848f-8e1ce3e8cfaa",
    "Content-Length": "344"
  },
  "body": {
    "target_id": 802281907,
    "target_type": "fr_test",
    "case_project_id": "CP-00009",
    "generation_stage": "test_point.generated",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "generation_status": "generating",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_progress": 52,
    "generation_updated_at": "2026-09-07T17:32:58.594279+00:00"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 6: /api/case-service/callbacks/generation-status

```json
{
  "received_at": "2026-09-07T17:34:03.471974+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/generation-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "53a84b34-10eb-4a3c-887d-ec8cc98cc606",
    "Content-Length": "343"
  },
  "body": {
    "target_id": 802281907,
    "target_type": "fr_test",
    "case_project_id": "CP-00009",
    "generation_stage": "test_case.generated",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "generation_status": "generating",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_progress": 72,
    "generation_updated_at": "2026-09-07T17:34:02.429479+00:00"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 7: /api/case-service/callbacks/generation-status

```json
{
  "received_at": "2026-09-07T17:34:03.485075+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/generation-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "072848db-c418-470c-894c-68fc9b02f879",
    "Content-Length": "346"
  },
  "body": {
    "target_id": 802281907,
    "target_type": "fr_test",
    "case_project_id": "CP-00009",
    "generation_stage": "quality.completed",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "generation_status": "awaiting_review",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_progress": 96,
    "generation_updated_at": "2026-09-07T17:34:02.454024+00:00"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 8: /api/case-service/callbacks/generation-status

```json
{
  "received_at": "2026-09-07T17:34:03.496042+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/generation-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "ad2707b8-7b49-4b1f-91ad-80f875949518",
    "Content-Length": "332"
  },
  "body": {
    "target_id": 802281907,
    "target_type": "fr_test",
    "case_project_id": "CP-00009",
    "generation_stage": "completed",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "generation_status": "approved",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_progress": 100,
    "generation_updated_at": "2026-09-07T17:34:02.457869+00:00"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 9: /api/case-service/callbacks/case-summary

```json
{
  "received_at": "2026-09-07T17:34:03.507149+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/case-summary",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "1dd76251-48ff-4720-a379-50f09f0f173b",
    "Content-Length": "2176"
  },
  "body": {
    "cases": {
      "CP-00009-CASE-001": {
        "stage": "L0",
        "title": "正常网络环境下设备所有者说话人分离识别验证",
        "test_domain": [
          "功能测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual"
      },
      "CP-00009-CASE-002": {
        "stage": "L2",
        "title": "离线网络环境下设备所有者说话人分离功能验证",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual"
      },
      "CP-00009-CASE-003": {
        "stage": "L2",
        "title": "高抖动弱网环境下设备所有者说话人分离功能验证",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual"
      },
      "CP-00009-CASE-004": {
        "stage": "L2",
        "title": "离线网络恢复正常后设备所有者说话人分离功能自动恢复验证",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual"
      },
      "CP-00009-CASE-005": {
        "stage": "L2",
        "title": "高抖动弱网恢复正常后设备所有者说话人分离功能自动恢复验证",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual"
      },
      "CP-00009-CASE-006": {
        "stage": "L4",
        "title": "设备所有者说话人分离功能连续运行1小时稳定性验证",
        "test_domain": [
          "稳定性测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual"
      },
      "CP-00009-CASE-007": {
        "stage": "L2",
        "title": "离线网络环境下多次触发设备所有者说话人分离功能验证",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual"
      },
      "CP-00009-CASE-008": {
        "stage": "L2",
        "title": "高抖动弱网环境下多次触发设备所有者说话人分离功能验证",
        "test_domain": [
          "异常场景测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual"
      },
      "CP-00009-CASE-009": {
        "stage": "L4",
        "title": "多次在离线和正常网络间切换后功能恢复验证",
        "test_domain": [
          "异常恢复测试",
          "音频说话人分离模块"
        ],
        "automation_type": "manual"
      }
    },
    "target_id": 802281907,
    "target_type": "fr_test",
    "case_project_id": "CP-00009",
    "case_platform_url": "http://127.0.0.1:3000/case-projects/CP-00009",
    "generation_status": "approved",
    "case_generation_id": "CASE-SESSION-00012",
    "generation_updated_at": "2026-09-07T17:34:02.457869+00:00"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 10: /api/case-service/callbacks/task-status

```json
{
  "received_at": "2026-09-07T17:34:05.472148+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/task-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "9ed9f959-f461-4dc3-9f4d-0be3e45a4a52",
    "Content-Length": "1066"
  },
  "body": {
    "task": {
      "cases": {
        "CP-00009-CASE-001": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535617+00:00"
        },
        "CP-00009-CASE-002": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535628+00:00"
        },
        "CP-00009-CASE-003": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535633+00:00"
        },
        "CP-00009-CASE-004": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535638+00:00"
        },
        "CP-00009-CASE-005": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535645+00:00"
        },
        "CP-00009-CASE-007": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535650+00:00"
        },
        "CP-00009-CASE-008": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535654+00:00"
        }
      },
      "status": "confirmed",
      "tester": "executor@casepilot.local",
      "task_id": "TASK-00008",
      "task_name": "FR-REVIEW-802281907 execution",
      "updated_at": "2026-09-07T17:34:04.586957+00:00",
      "cases_complete": true,
      "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4"
    },
    "target_id": 802281907,
    "target_type": "fr_test"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 11: /api/case-service/callbacks/task-status

```json
{
  "received_at": "2026-09-07T17:34:05.486879+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/task-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "1e2d4cb3-c6bf-42cd-b801-1bb9e80eef84",
    "Content-Length": "1064"
  },
  "body": {
    "task": {
      "cases": {
        "CP-00009-CASE-001": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535617+00:00"
        },
        "CP-00009-CASE-002": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535628+00:00"
        },
        "CP-00009-CASE-003": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535633+00:00"
        },
        "CP-00009-CASE-004": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535638+00:00"
        },
        "CP-00009-CASE-005": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535645+00:00"
        },
        "CP-00009-CASE-007": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535650+00:00"
        },
        "CP-00009-CASE-008": {
          "cr": "",
          "jira": "",
          "status": "not_run",
          "updated_at": "2026-09-07T17:34:04.535654+00:00"
        }
      },
      "status": "running",
      "tester": "executor@casepilot.local",
      "task_id": "TASK-00008",
      "task_name": "FR-REVIEW-802281907 execution",
      "updated_at": "2026-09-07T17:34:04.636593+00:00",
      "cases_complete": true,
      "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4"
    },
    "target_id": 802281907,
    "target_type": "fr_test"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

### Callback 12: /api/case-service/callbacks/task-status

```json
{
  "received_at": "2026-09-07T17:34:05.498444+00:00",
  "method": "POST",
  "path": "/api/case-service/callbacks/task-status",
  "headers": {
    "Host": "casepilot-callback-mock:8090",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "User-Agent": "python-httpx/0.28.1",
    "Authorization": "Bearer ***",
    "Content-Type": "application/json",
    "X-Callback-Event-ID": "e633b3c6-89d5-4a90-8a00-69d44740ec0a",
    "Content-Length": "1059"
  },
  "body": {
    "task": {
      "cases": {
        "CP-00009-CASE-001": {
          "cr": "",
          "jira": "",
          "status": "passed",
          "updated_at": "2026-09-07T17:34:06.673753+00:00"
        },
        "CP-00009-CASE-002": {
          "cr": "",
          "jira": "",
          "status": "passed",
          "updated_at": "2026-09-07T17:34:06.673753+00:00"
        },
        "CP-00009-CASE-003": {
          "cr": "",
          "jira": "",
          "status": "passed",
          "updated_at": "2026-09-07T17:34:06.673753+00:00"
        },
        "CP-00009-CASE-004": {
          "cr": "",
          "jira": "",
          "status": "passed",
          "updated_at": "2026-09-07T17:34:06.673753+00:00"
        },
        "CP-00009-CASE-005": {
          "cr": "",
          "jira": "",
          "status": "passed",
          "updated_at": "2026-09-07T17:34:06.673753+00:00"
        },
        "CP-00009-CASE-007": {
          "cr": "",
          "jira": "",
          "status": "passed",
          "updated_at": "2026-09-07T17:34:06.673753+00:00"
        },
        "CP-00009-CASE-008": {
          "cr": "",
          "jira": "",
          "status": "passed",
          "updated_at": "2026-09-07T17:34:06.673753+00:00"
        }
      },
      "status": "completed",
      "tester": "executor@casepilot.local",
      "task_id": "TASK-00008",
      "task_name": "FR-REVIEW-802281907 execution",
      "updated_at": "2026-09-07T17:34:06.673753+00:00",
      "cases_complete": true,
      "task_request_id": "8be5a0e9-4a07-402a-949c-83852147eac4"
    },
    "target_id": 802281907,
    "target_type": "fr_test"
  },
  "response": {
    "status": 204,
    "body": null
  }
}
```

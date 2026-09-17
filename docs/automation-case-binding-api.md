# 自动化用例绑定上传接口

一条测试用例可以绑定多条自动化用例。上传接口接收 JSON 数组，并将数组完整保存为该用例的当前绑定清单。绑定随用例 Revision 保存；上传有变化时生成新 Revision，历史 Revision 仍保留原绑定。

## 上传

`POST /api/v1/test-cases/{case_id}/automation-cases/upload`

请求头使用 `Content-Type: application/json`，并携带现有登录会话 Cookie。`case_id` 为平台测试用例 UUID，调用者需属于该用例所在空间。请求体为数组，最多 100 条：

```json
[
  {
    "creator": "张三",
    "git": "https://github.com/example/automation.git",
    "branch": "main",
    "commit": "8c4f0b4d9a7b6a1e0123456789abcdef01234567",
    "case_name": "tests/login/test_valid_login.py::test_valid_login",
    "update_time": "2026-09-17T10:30:00+08:00",
    "create_time": "2026-09-10T09:00:00+08:00"
  },
  {
    "creator": "李四",
    "git": "https://github.com/example/automation.git",
    "branch": "release/1.0",
    "commit": "bb99a4c9a7b6a1e0123456789abcdef012345678",
    "case_name": "tests/login/test_invalid_login.py::test_invalid_login",
    "update_time": "2026-09-17T11:00:00+08:00",
    "create_time": "2026-09-12T09:00:00+08:00"
  }
]
```

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `creator` | string | 必填，1–160 字符 | 自动化用例维护人 |
| `git` | string | 必填，1–500 字符 | Git 仓库地址 |
| `branch` | string | 必填，1–160 字符 | Git 分支 |
| `commit` | string | 必填，1–160 字符 | Git commit SHA |
| `case_name` | string | 必填，1–500 字符 | 仓库内的自动化用例名称或唯一标识 |
| `update_time` | ISO 8601 datetime | 必填，带时区 | 最近更新时间 |
| `create_time` | ISO 8601 datetime | 必填，带时区 | 创建时间 |

五个字符串字段会去除首尾空白，不能仅包含空白。`update_time` 不得早于 `create_time`。同一上传数组中，`git + branch + case_name` 不可重复；同一仓库分支中的不同用例需使用不同的 `case_name`。

每次上传**替换**当前绑定清单；传 `[]` 清除全部绑定。非空清单会将 `automation_type` 设为 `automated`，空清单设为 `manual`。相同清单重复上传不会增加 Revision。成功时返回完整的 `TestCaseView`，其中包含 `automation_cases`、`automation_type`、`current_revision_id` 和 `revision_number`。也可使用 `GET /api/v1/test-cases/{case_id}` 读取最新绑定。

## 响应与错误

| HTTP 状态 | 含义 |
| --- | --- |
| `200` | 上传成功；返回完整用例，含保存后的绑定清单 |
| `401` | 未登录或会话无效 |
| `403` | 当前账号不属于用例所在空间 |
| `404` | 用例不存在或已删除 |
| `422` | 字段校验失败、更新时间早于创建时间，或数组内有重复的 `git + branch + case_name` |
| `409` | 用例当前 Revision 不存在 |

接口在服务的 `/docs` 和 `/openapi.json` 中提供请求模型与字段说明。当前接口存储绑定信息，不校验远程 Git 仓库或 commit 是否存在。

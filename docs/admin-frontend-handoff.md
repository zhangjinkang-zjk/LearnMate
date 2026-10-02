# 管理员前端交接

前端页面已实现，后端同事继续负责接口完善、部署和联调。页面没有使用模拟用户数据，也不把任务、角色、活跃度持久化到 localStorage。原有后端改动保留在既有提交中，本轮仅收尾前端。

## 页面入口

| 地址（站点 URL 的 `#` 后） | 功能 |
| --- | --- |
| `/admin?tab=resources` | 资源搜索、审核状态筛选、完整预览、原文编辑、通过、驳回、删除 |
| `/admin?tab=accounts` | 账号搜索、学校/年级/专业编辑、重置密码、删除普通账号 |
| `/admin?tab=activity` | 7/30 天汇总、全站排行、活跃/不活跃筛选、个人学习明细 |
| `/admin?tab=push` | 跨页选择最多 100 人、搜索并选择公开资源、附带建议推送 |
| `/learning/assignments` | 用户查看待完成/已完成任务、打开资源、标记完成 |
| `/learning/assignments?task=123` | 通知点击进入任务，并自动打开对应资源 |

管理员从普通登录页登录，登录响应 `role=admin` 时默认进入管理中心；侧边栏根据 `/user/read_user` 的真实角色显示入口。访问 `/admin` 时再次向服务端验证角色。前端检查不能代替后端鉴权。

## 公共约定

- 请求统一通过 `frontend/src/shared/api/httpClient.js`，携带 `Authorization: Bearer <token>` 及兼容的 `token` header。实际后端地址由该现有客户端配置。
- 管理员、任务接口封装位于 `frontend/src/shared/api/adminApi.js`。页面不拼接后端地址。
- 成功信封为 `{ "code": 200, "data": ... }`；无数据的写操作可省略 `data`。
- 业务失败可返回非 200 的 `code` 与中文 `msg`，也支持 HTTP 错误中的字符串 `detail`。HTTP 401 由现有公共客户端清理登录并跳转。
- 时间字段使用带时区的 ISO 8601 字符串；无记录返回 `null`，不能用注册时间代替最近登录。
- 列表分页从 1 开始，每页 20 条。后台做搜索、筛选和分页，不要仅返回当前页后再计算全站排名。

## 资源审核

| 方法与接口 | 请求 | 成功 `data` |
| --- | --- | --- |
| `GET /admin/resource-catalog` | `search`, `visibility`（可省略）, `page`, `pushable`（推送选资源时为 true） | `{ items: Resource[], total: number, pending: number }` |
| `GET /admin/resources/{id}/detail` | 无 | 完整 Resource，必须包含原始 `content` |
| `PUT /admin/resources/{id}` | `{ topic, content }` | 更新后的资源（前端以写入成功为准） |
| `POST /admin/resources/applications/{id}/approve` | `{ reason: "" }` | 审核后的资源 |
| `POST /admin/resources/applications/{id}/reject` | `{ reason }` | 审核后的资源 |
| `DELETE /admin/resources/{id}` | 无 | 可省略 |

Resource 使用字段：`resource_id`, `topic`, `resource_type`, `visibility`, `owner_user_id`, `updated_at`, `content`, `file_url`。`visibility` 为 `pending/public/private/rejected`。正文仅在详情返回即可；编辑时不能以预览摘要替代完整正文。标题最大 255 字符，正文最大 2,000,000 字符，驳回原因最大 1,000 字符。

前端支持文档、PPT、思维导图、音频、视频文件、图片预览；外部资源提供打开链接。相对文件地址只解析 `/static/`；其他文件地址需为完整 HTTP(S) URL。

审核写入需由后端检查待审核状态；如果已被其他管理员处理，返回 409。通过时应同步公开状态与审核状态；驳回原因需通知提交者。推送资源选择器只返回审核通过的公开资源。

## 账号与活跃度

| 方法与接口 | 请求 | 成功 `data` |
| --- | --- | --- |
| `GET /admin/activity` | `search`, `days=7/30`, `activity=all/active/inactive`, `sort=study_seconds/active_days`, `page` | `{ items: Account[], total, summary, days }` |
| `GET /admin/users/{id}/activity` | 无 | `{ sessions: [{ date, total_seconds }], resources: [{ resource_id, title, is_read, read_at, duration_seconds }] }` |
| `PUT /admin/users/{id}` | `{ university, grade, major }` | 更新结果 |
| `POST /admin/users/{id}/reset_password` | `{ new_password }` | 可省略 |
| `DELETE /admin/users/{id}` | `{ confirm: true }` | 可省略 |

Account 使用字段：`id`, `username`, `role`, `email`, `university`, `grade`, `major`, `created_at`, `rank`, `active_days`, `study_seconds`, `last_login_at`, `last_active_at`, `is_active`。

`summary` 为 `{ total_users, active_users, study_seconds }`，表示全站所选时间范围汇总，不随当前搜索/分页缩小。`rank` 为所选排序在全站的名次，搜索后保留原名次。个人详情需要近 30 天每日学习秒数，以及最近最多 30 条资源学习记录。

前端学校/年级/专业长度限制分别为 100/20/200；密码至少 8 个字符且 UTF-8 不超过 72 字节。确认密码不发送到后端，不保存、不展示明文密码。管理员账号不提供删除按钮；服务端仍须独立校验。密码哈希、重置后的既有会话处理和账号删除关联数据策略由后端负责。

## 推送与学习任务

| 方法与接口 | 请求 | 成功 `data` |
| --- | --- | --- |
| `POST /admin/resource-pushes` | `{ resource_id, user_ids: number[], message }` | `{ created: number, skipped: number }` |
| `GET /study/assignments` | 当前登录用户 | `Assignment[]` |
| `GET /resource/{id}` | 当前登录用户 | 完整资源正文与文件地址，沿用既有资源接口 |
| `POST /study/assignments/{id}/complete` | 无 | 更新后的完整 Assignment |

Assignment 使用字段：`id`, `title`, `message`, `resource_id`, `resource_type`, `is_available`, `created_at`, `completed_at`。未完成时 `completed_at=null`。

前端批量选择上限 100 人；推送备注最大 1,000 字符。同一用户已有相同资源任务时跳过，使用返回的计数向管理员反馈。

通知与任务必须在服务端同一事务保存，通知为定向消息，`target_url` 使用 `/learning/assignments?task={任务ID}`，不能写成旧版路径。推送不应把私人资源自动变为公开资源。读取/完成任务必须按当前登录用户隔离。资源删除或下架后保留任务标题，返回 `is_available=false`；前端会禁用查看和完成按钮。

## 联调重点与验证边界

前端构建与 `git diff --check` 可独立运行；当前浏览器工具未连接，未完成桌面/移动真实截图验收。页面已包含响应式表格滚动、弹窗、加载/空态/错误重试、未保存确认和提交禁用。

后端接手后应实际验证：普通用户/失效 token 的权限、并发审核、密码重置、排行榜时间边界、重复推送、通知与任务事务、跨账号任务访问、资源下架后的任务状态。工作区中 `backend/tests/test_admin_management.py` 是上一轮准备的未执行测试草稿，未纳入本轮前端提交。

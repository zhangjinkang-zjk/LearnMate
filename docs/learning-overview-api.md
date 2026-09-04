# 学习概览接口说明

更新时间：2026-09-05

本文档记录学习概览页面使用的后端接口。概览页面只需要调用聚合接口，后端负责读取画像、路径、科目进度、诊断和学习记录，前端不再并行拼接多个接口，也不在读取页面时生成学习路径。

## 1. 鉴权约定

所有接口都需要登录用户的 JWT。

```http
Authorization: Bearer <access_token>
```

为兼容旧客户端，也可以同时携带：

```http
token: <access_token>
```

未登录或 token 失效时返回 HTTP `401`。前端应清理本地登录状态并回到登录页，不要把 token 放到 URL、日志或错误提示中。

## 2. 概览主接口

### `GET /study/overview`

返回当前用户的学习概览快照。请求不需要 query 参数或 request body。

```http
GET /study/overview
```

统一响应包装：

```json
{
  "code": 200,
  "msg": "success",
  "data": {}
}
```

### 2.1 返回字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `profile` | object | 用户首次学习定向保存的身份、方向和目标 |
| `path` | object | 当前学习路径、整体节点进度和路径内相对难度序列 |
| `subjects` | array | 用户已加入路径对应的科目完成度和学习时长 |
| `goals` | array | 当前路径节点清单，可用于目标勾选列表 |
| `next_content` | array | 当前处于进行中或已解锁状态的下一步内容 |
| `blind_spots` | array | 按掌握度筛选后的薄弱知识点 |
| `diagnosis` | object | 当前综合掌握度、阶段和已作答数量 |
| `mastery_bars` | array | 图表用知识点掌握度数据；没有练习记录时使用六维能力 |
| `radar` | object | 记忆、理解、应用、分析、广度、坚持六维能力数据 |
| `study_history` | array | 最近 7 天实际累计学习时长，可用于学习轨迹图 |
| `summary` | object | 学习总时长、活跃天数、节点完成数和掌握度摘要 |
| `recommendation` | object | 当前系统判断、推荐行动、推荐理由和完成标准 |

示例：

```json
{
  "profile": {
    "identity": "应届毕业生",
    "direction": "大模型应用",
    "goal": "完成一个可验证的项目"
  },
  "path": {
    "id": 12,
    "progress": 40,
    "completed_nodes": 2,
    "total_nodes": 5,
    "difficulty_trend": [
      {"id": 101, "order_index": 1, "title": "文档切分", "status": "completed", "difficulty_score": 1.0, "relative_difficulty": 20},
      {"id": 102, "order_index": 2, "title": "召回结果排查", "status": "unlocked", "difficulty_score": 1.8, "relative_difficulty": 90}
    ]
  },
  "subjects": [
    {
      "id": 12,
      "name": "RAG",
      "progress": 44,
      "completed_nodes": 2,
      "total_nodes": 5,
      "study_seconds": 11400
    }
  ],
  "goals": [
    {"id": 101, "title": "文档切分", "status": "completed", "progress": 100},
    {"id": 102, "title": "召回结果排查", "status": "unlocked", "progress": 0}
  ],
  "next_content": [
    {"id": 102, "title": "召回结果排查", "status": "unlocked"}
  ],
  "blind_spots": [
    {"tag": "向量检索", "accuracy": 44, "level": "learning"}
  ],
  "diagnosis": {
    "score": 58,
    "stage": "基础建立期",
    "answered": 6
  },
  "mastery_bars": [
    {"label": "向量检索", "score": 44, "type": "knowledge", "attempts": 9, "correct_count": 4}
  ],
  "radar": {
    "dimensions": [
      {"key": "memory", "label": "记忆", "score": 60, "desc": "简单题正确率"}
    ]
  },
  "study_history": [
    {"date": "2026-08-30", "study_seconds": 1800}
  ],
  "summary": {
    "total_study_seconds": 11400,
    "active_days": 4,
    "completed_nodes": 2,
    "total_nodes": 5,
    "mastery_score": 58,
    "text": "已记录 3 个知识点的练习，综合掌握度为 58%。当前优先关注“向量检索”，先补强后再进入下一步。"
  },
  "recommendation": {
    "judgement": "当前主要短板是向量检索能力",
    "action": "召回结果排查",
    "reason": "向量检索当前正确率约 44%，先补强该知识点能减少后续反复。",
    "criteria": "能够解释“召回结果排查”的关键方法，并通过节点测验。",
    "target_id": 102,
    "action_type": "read",
    "status": "ready"
  }
}
```

### 2.2 空数据约定

用户尚未完成学习定向、尚未生成路径或没有练习记录时，接口仍返回 `200`，但对应字段为空或为 `null`：

- `subjects`、`goals`、`next_content`、`blind_spots`、`study_history`、`mastery_bars` 返回空数组；
- `path.id` 可以为 `null`，进度为 `0`；
- 没有当前路径时 `path.difficulty_trend` 返回空数组；有路径时首节点的 `difficulty_score` 固定为 `1.0`，`relative_difficulty` 仅用于当前路径内的图表高度；
- `diagnosis.score`、`summary.mastery_score` 可以为 `null`，`diagnosis.stage` 为 `正在生成`，`summary.text` 为空字符串；
- `recommendation.status` 为 `generating`，没有可执行节点时 `target_id` 和 `action` 为 `null`。

前端应根据这些字段显示“正在生成”或空状态，不能填充示例科目、进度、时长或推荐结论。

## 3. 聚合接口读取的现有数据接口

以下接口仍然保留，供其他页面或后端服务使用。学习概览页面不需要直接调用它们；`GET /study/overview` 已在服务端完成聚合。

| 接口 | 用途 | 主要数据 |
| --- | --- | --- |
| `GET /ai_portrait/read_portrait` | 读取用户画像 | 身份、学习方向、学习目标、画像 traits |
| `GET /ai_portrait/radar` | 读取或计算能力雷达 | 记忆、理解、应用、分析、广度、坚持 |
| `GET /learning_path/current` | 读取当前活跃路径 | 节点、节点状态、当前节点、路径诊断 |
| `GET /study/path-stats` | 分路径统计 | 科目完成度、学习时长、路径薄弱点 |
| `GET /study/stats` | 全局学习统计 | 总学习时长、答题统计、薄弱知识点、资源统计 |

其中 `GET /study/overview` 只读这些现有数据，不会调用路径生成接口，不会新增路径或节点，也不会修改用户学习状态。

## 4. 实现位置

- Router：`backend/src/router/study_router.py`
- Service：`backend/src/service/study/service.py` 的 `StudyService.get_overview`
- JWT 依赖：`backend/src/utils/jwt.py` 的 `get_user_id_from_token`

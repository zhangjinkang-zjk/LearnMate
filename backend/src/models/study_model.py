"""学习统计相关模型 — 学习时长、资源已读"""

from tortoise import Model, fields


class StudySession(Model):
    """每日学习时长表（心跳聚合）"""
    id = fields.IntField(pk=True)
    date = fields.DateField(description="日期")
    total_seconds = fields.IntField(default=0, description="当日累计学习秒数")
    last_heartbeat_at = fields.DatetimeField(null=True)
    path_id = fields.IntField(null=True, description="关联的学习路径ID，用于分路径统计")

    user = fields.ForeignKeyField("models.User", related_name="study_sessions", on_delete=fields.CASCADE)

    class Meta:
        table = "study_sessions"
        unique_together = [("user_id", "date")]


class ResourceReadStatus(Model):
    """资源已读标记 + 使用时长"""
    id = fields.IntField(pk=True)
    is_read = fields.BooleanField(default=False)
    read_at = fields.DatetimeField(null=True)
    duration_seconds = fields.IntField(default=0, description="累计使用时长（秒）")

    user = fields.ForeignKeyField("models.User", related_name="resource_reads", on_delete=fields.CASCADE)
    resource = fields.ForeignKeyField("models.GeneratedResource", related_name="read_statuses", on_delete=fields.CASCADE)

    class Meta:
        table = "resource_read_status"
        unique_together = [("user_id", "resource_id")]


class ResourceCollection(Model):
    """资源收藏"""
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    user = fields.ForeignKeyField("models.User", related_name="resource_collections", on_delete=fields.CASCADE)
    resource = fields.ForeignKeyField("models.GeneratedResource", related_name="collections", on_delete=fields.CASCADE)

    class Meta:
        table = "resource_collections"
        unique_together = [("user_id", "resource_id")]


class ResourceLike(Model):
    """资源点赞"""
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    user = fields.ForeignKeyField("models.User", related_name="resource_likes", on_delete=fields.CASCADE)
    resource = fields.ForeignKeyField("models.GeneratedResource", related_name="likes", on_delete=fields.CASCADE)

    class Meta:
        table = "resource_likes"
        unique_together = [("user_id", "resource_id")]


class LearningEvent(Model):
    """学习行为事件，用于持续更新画像并追踪推荐依据。"""

    id = fields.IntField(pk=True)
    event_type = fields.CharField(max_length=32, description="事件类型: assessment/node_quiz/classroom_chat/chat/resource_read")
    path_id = fields.IntField(null=True, description="关联学习路径")
    node_id = fields.IntField(null=True, description="关联路径节点")
    knowledge_tags = fields.TextField(null=True, description="关联知识点标签 JSON 数组")
    score = fields.FloatField(null=True, description="本次行为得分 0-100")
    evidence = fields.TextField(null=True, description="用户留下的学习证据摘要")
    metadata = fields.TextField(null=True, description="事件附加信息 JSON")
    created_at = fields.DatetimeField(auto_now_add=True)

    user = fields.ForeignKeyField(
        "models.User",
        related_name="learning_events",
        on_delete=fields.CASCADE,
    )

    class Meta:
        table = "learning_events"
        ordering = ["-created_at"]

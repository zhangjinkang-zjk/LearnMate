"""进阶学习巩固会话模型。"""

from tortoise import Model, fields


class AdvancedPracticeSession(Model):
    """保存一次进阶实践对话，支持暂存、恢复和最终提交。"""

    id = fields.IntField(pk=True)
    session_key = fields.CharField(max_length=64, unique=True, description="对外暴露的会话 ID")
    task_key = fields.CharField(max_length=128, description="进阶任务快照中的任务 ID")
    path_id = fields.IntField(description="关联学习路径 ID")
    node_id = fields.IntField(description="关联学习节点 ID")
    task_snapshot = fields.JSONField(description="创建会话时的任务快照")
    status = fields.CharField(max_length=16, default="active", description="active/paused/completed")
    current_phase = fields.CharField(max_length=32, default="understand")
    completed_phases = fields.JSONField(default=list)
    messages = fields.JSONField(default=list, description="对话消息快照")
    confirmed_facts = fields.JSONField(default=list, description="已确认事实")
    assumptions = fields.JSONField(default=list, description="待验证假设")
    final_submission = fields.TextField(null=True, description="用户提交的最终方案")
    evaluation = fields.JSONField(null=True, description="提交后的评价结果")
    started_at = fields.DatetimeField(auto_now_add=True)
    ended_at = fields.DatetimeField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)

    user = fields.ForeignKeyField(
        "models.User",
        related_name="advanced_practice_sessions",
        on_delete=fields.CASCADE,
    )

    class Meta:
        table = "advanced_practice_sessions"
        unique_together = [("user_id", "task_key", "path_id", "node_id")]

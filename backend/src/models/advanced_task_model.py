"""Persist the latest milestone-based advanced practice task set."""

from tortoise import Model, fields


class AdvancedTaskSnapshot(Model):
    """One generated task set for a user's learning milestone."""

    id = fields.IntField(pk=True)
    milestone = fields.IntField(description="里程碑序号：每完成 10 个基础节点递增")
    completed_nodes = fields.IntField(default=0, description="生成时已完成的基础节点数")
    current_node_id = fields.IntField(null=True, description="生成时关联的当前路径节点")
    task_json = fields.JSONField(description="进阶任务智能体输出的任务快照")
    source = fields.CharField(max_length=16, default="agent", description="agent/fallback")
    generation_error = fields.CharField(max_length=500, null=True, description="智能体失败时的内部摘要")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    user = fields.ForeignKeyField(
        "models.User",
        related_name="advanced_task_snapshots",
        on_delete=fields.CASCADE,
    )
    path = fields.ForeignKeyField(
        "models.LearningPath",
        related_name="advanced_task_snapshots",
        on_delete=fields.CASCADE,
    )

    class Meta:
        table = "advanced_task_snapshots"
        unique_together = [("user_id", "path_id", "milestone")]

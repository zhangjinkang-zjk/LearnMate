"""进阶学习巩固会话模型。"""

from tortoise import Model, fields


class AdvancedPracticeSession(Model):
    """保存一次进阶实践对话，支持暂存和恢复。

    **这个表只管账本**：谁跟哪个任务聊过、聊了什么。阶段与判分的那五列
    （`current_phase` / `completed_phases` / `deliverable_state` / `final_submission` /
    `evaluation`）已经删掉了 —— 它们曾是阶段机的存储，没有任何读写者，留着只会让人
    以为会话记得一套流程，从而照着再写一遍。库里那五列由
    `utils/database.py` 的 `_drop_advanced_practice_phase_columns()` 在启动时清掉。

    **别再往这张表加"进度"类字段。** 学习进度不在这里，也不该存在任何地方 ——
    它由学生在工作区里真正写出来的文件推导（见 `系统设计.md` 第 8 节），
    存成状态就会像 `current_phase` 那样永远停在起点。
    """

    id = fields.IntField(pk=True)
    session_key = fields.CharField(max_length=64, unique=True, description="对外暴露的会话 ID")
    task_key = fields.CharField(max_length=128, description="进阶任务快照中的任务 ID")
    path_id = fields.IntField(description="关联学习路径 ID")
    node_id = fields.IntField(description="关联学习节点 ID")
    task_snapshot = fields.JSONField(description="创建会话时的任务快照")
    status = fields.CharField(max_length=16, default="active", description="active/paused/completed")
    messages = fields.JSONField(default=list, description="对话消息快照")
    confirmed_facts = fields.JSONField(default=list, description="已确认事实（已无读者）")
    assumptions = fields.JSONField(default=list, description="待验证假设（已无读者）")
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

"""进阶学习巩固会话模型。"""

from tortoise import Model, fields


class AdvancedPracticeSession(Model):
    """保存一次进阶实践对话，支持暂存和恢复。

    下面五列（`current_phase` / `completed_phases` / `deliverable_state` /
    `final_submission` / `evaluation`）是阶段机与判分留下的**遗迹**，代码里已经没有
    任何读写者。**故意不删**：`completed_phases` 在库里是 `NOT NULL` 且没有默认值，
    从 model 里拿掉就会让 INSERT 直接失败，而删列必须先 `MODIFY ... NULL`、发布、
    再 `DROP`，一次要卡两个发布窗口 —— 为了清掉几个空列不值得。
    """

    id = fields.IntField(pk=True)
    session_key = fields.CharField(max_length=64, unique=True, description="对外暴露的会话 ID")
    task_key = fields.CharField(max_length=128, description="进阶任务快照中的任务 ID")
    path_id = fields.IntField(description="关联学习路径 ID")
    node_id = fields.IntField(description="关联学习节点 ID")
    task_snapshot = fields.JSONField(description="创建会话时的任务快照")
    status = fields.CharField(max_length=16, default="active", description="active/paused/completed")
    # ── 以下是遗迹，为兼容库表而保留，别再往里写 ──
    current_phase = fields.CharField(max_length=32, default="understand")
    completed_phases = fields.JSONField(default=list)
    deliverable_state = fields.JSONField(default=dict)
    final_submission = fields.TextField(null=True)
    evaluation = fields.JSONField(null=True)
    # ── 遗迹结束 ──
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

"""用户自建智能体模型"""

from tortoise import Model, fields


class UserAgent(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField("models.User", related_name="agents", on_delete=fields.CASCADE)

    name = fields.CharField(max_length=64, description="智能体名称")
    avatar = fields.CharField(max_length=512, default="", description="头像URL")
    persona = fields.TextField(default="", description="角色设定(system prompt)")
    tools = fields.TextField(default="[]", description="已选工具名称列表(JSON)")
    memory = fields.TextField(default="[]", description="对话记忆摘要(JSON)")
    schedule = fields.TextField(null=True, description="定时任务配置(JSON)")

    is_public = fields.BooleanField(default=False, description="是否公开到市场")
    enabled = fields.BooleanField(default=True)
    is_system = fields.BooleanField(default=False, description="系统内置智能体，禁止用户编辑/删除")
    # 内置领域智能体的**稳定标识**（见 `service/agent/domain_agents.py`）。用户自建的为空。
    #
    # 判别"这条系统行是哪个领域"只能靠它，不能靠 name：name 是给人看的、将来会改（现在
    # `get_or_create_domain_agent` 就会用代码里的名字覆盖它），而一个用户身上会有**多条**
    # 系统行（开发教练、幼师导师…）—— "取那条 is_system 的行"从此不再唯一，取错就是把
    # 学幼师的学生接给了写代码的教练。
    agent_key = fields.CharField(
        max_length=32, null=True, description="内置领域智能体标识；用户自建的为 NULL"
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "user_agents"

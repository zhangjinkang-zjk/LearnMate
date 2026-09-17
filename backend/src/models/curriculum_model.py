"""课程体系模型 — 学习方向 → 要学的课程/知识单元"""

from tortoise import Model, fields


class CurriculumCourse(Model):
    id = fields.IntField(pk=True)
    # 缓存键是"方向"本身（"机械制图"、"企业知识库与智能体应用开发"），专业也走同一条路：
    # 对这张表来说两者是同一件事 —— 一串要学的清单。以前这里还有 grade，但
    # sys_user.grade 一直是 NULL、表里也一行都没有，那个维度从来没被用过。
    direction = fields.CharField(max_length=128, description="学习方向或专业")
    courses = fields.TextField(description="课程/知识单元列表，JSON 数组字符串")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "curriculum_courses"
        unique_together = [("direction",)]

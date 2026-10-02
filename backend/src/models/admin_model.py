"""Administrator assignments and account login observations."""
from tortoise import Model, fields


class AccountLogin(Model):
    id = fields.IntField(pk=True)
    user = fields.OneToOneField("models.User", related_name="login_observation", on_delete=fields.CASCADE)
    last_login_at = fields.DatetimeField()

    class Meta:
        table = "account_logins"


class ResourceAssignment(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField("models.User", related_name="resource_assignments", on_delete=fields.CASCADE)
    resource = fields.ForeignKeyField("models.GeneratedResource", related_name="assignments", null=True, on_delete=fields.SET_NULL)
    assigned_by = fields.ForeignKeyField("models.User", related_name="sent_assignments", null=True, on_delete=fields.SET_NULL)
    title = fields.CharField(max_length=255)
    message = fields.CharField(max_length=1000, default="")
    created_at = fields.DatetimeField(auto_now_add=True)
    completed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "resource_assignments"
        unique_together = [("user", "resource")]

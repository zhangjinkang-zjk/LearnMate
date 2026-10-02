"""Historical snapshots for the six-dimension portrait radar."""

from tortoise import Model, fields


class PortraitRadarHistory(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="radar_history",
        on_delete=fields.CASCADE,
    )

    memory = fields.IntField(default=0)
    understanding = fields.IntField(default=0)
    application = fields.IntField(default=0)
    analysis = fields.IntField(default=0)
    breadth = fields.IntField(default=0)
    persistence = fields.IntField(default=0)
    snapshot_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "portrait_radar_history"

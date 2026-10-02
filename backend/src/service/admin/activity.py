"""Read activity from persisted study evidence; never infer login from profile edits."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from tortoise.functions import Max

from backend.src.models.admin_model import AccountLogin
from backend.src.models.study_model import LearningEvent, ResourceReadStatus, StudySession
from backend.src.models.usermodel import User

LOCAL_ZONE = timezone(timedelta(hours=8))


async def record_login(user_id: int):
    await AccountLogin.update_or_create(
        user_id=user_id, defaults={"last_login_at": datetime.now(timezone.utc)},
    )


def serialize_time(value):
    return value.isoformat() if value else None


async def list_activity(options) -> dict:
    today = datetime.now(LOCAL_ZONE).date()
    start_day = today - timedelta(days=options.days - 1)
    start = datetime.combine(start_day, datetime.min.time(), tzinfo=LOCAL_ZONE)
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=LOCAL_ZONE)
    users = await User.all().values("id", "username", "role", "email", "university", "grade", "major", "created_at")
    logins = {row["user_id"]: row["last_login_at"] for row in await AccountLogin.all().values("user_id", "last_login_at")}
    sessions = await StudySession.filter(date__gte=start_day, date__lte=today, total_seconds__gt=0).values("user_id", "date", "total_seconds")
    events = await LearningEvent.filter(created_at__gte=start, created_at__lt=end).values("user_id", "created_at")
    recent = await StudySession.all().group_by("user_id").annotate(latest=Max("last_heartbeat_at")).values("user_id", "latest")
    last_activity = {row["user_id"]: row["latest"] for row in recent}
    last_events = await LearningEvent.all().group_by("user_id").annotate(latest=Max("created_at")).values("user_id", "latest")
    for row in last_events:
        previous = last_activity.get(row["user_id"])
        if previous is None or row["latest"] > previous:
            last_activity[row["user_id"]] = row["latest"]
    study_days, seconds = {}, {}
    for row in sessions:
        study_days.setdefault(row["user_id"], set()).add(row["date"])
        seconds[row["user_id"]] = seconds.get(row["user_id"], 0) + row["total_seconds"]
    for row in events:
        study_days.setdefault(row["user_id"], set()).add(row["created_at"].astimezone(LOCAL_ZONE).date())
    for user in users:
        user.update(
            active_days=len(study_days.get(user["id"], set())),
            study_seconds=seconds.get(user["id"], 0),
            last_login_at=serialize_time(logins.get(user["id"])),
            last_active_at=serialize_time(last_activity.get(user["id"])),
        )
        user["is_active"] = user["active_days"] > 0
    # Rank the complete population first, so searching does not renumber ranks.
    users.sort(key=lambda user: (-user[options.sort], -user["study_seconds"], user["id"]))
    for rank, user in enumerate(users, 1):
        user["rank"] = rank
    summary = {"total_users": len(users), "active_users": sum(user["is_active"] for user in users), "study_seconds": sum(seconds.values())}
    term = options.search.casefold()
    filtered = [user for user in users if
                (not term or term in f'{user["id"]} {user["username"]} {user["email"] or ""}'.casefold())
                and (options.activity == "all" or user["is_active"] == (options.activity == "active"))]
    offset = (options.page - 1) * options.size
    return {"items": filtered[offset:offset + options.size], "total": len(filtered), "summary": summary, "days": options.days}


async def get_user_activity(user_id: int) -> dict:
    if not await User.filter(id=user_id).exists():
        raise HTTPException(404, "用户不存在")
    today = datetime.now(LOCAL_ZONE).date()
    sessions = await StudySession.filter(user_id=user_id, date__gte=today - timedelta(days=29), date__lte=today).order_by("date").values("date", "total_seconds")
    reads = await ResourceReadStatus.filter(user_id=user_id).order_by("-read_at").limit(30).prefetch_related("resource")
    return {"sessions": sessions, "resources": [
        {"resource_id": row.resource_id, "title": row.resource.topic, "is_read": row.is_read,
         "read_at": serialize_time(row.read_at), "duration_seconds": row.duration_seconds} for row in reads
    ]}

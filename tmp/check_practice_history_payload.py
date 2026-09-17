"""Read-only: `_attach_practice_status` 在真实数据上给出什么。

把每个 (user, path) 当前快照的 tasks 喂进去，打印它挂上了哪些状态、又吐出了哪些
"历史实践"。只 SELECT，不写库。

Run: /f/anaconda3/envs/zhiban/python.exe tmp/check_practice_history_payload.py
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env")

from tortoise import Tortoise

MODULES = {
    "models": [
        "backend.src.models.usermodel",
        "backend.src.models.portraitmodel",
        "backend.src.models.portrait_radar_model",
        "backend.src.models.resource_model",
        "backend.src.models.path_model",
        "backend.src.models.exam_model",
        "backend.src.models.curriculum_model",
        "backend.src.models.study_model",
        "backend.src.models.notification_model",
        "backend.src.models.advanced_practice_model",
        "backend.src.models.advanced_task_model",
    ]
}


async def main() -> None:
    await Tortoise.init(db_url=os.environ["database"], modules=MODULES)

    from backend.src.models.advanced_task_model import AdvancedTaskSnapshot
    from backend.src.service.advanced.service import _attach_practice_status

    for snapshot in await AdvancedTaskSnapshot.all():
        payload = snapshot.task_json if isinstance(snapshot.task_json, dict) else {}
        tasks = [dict(t) for t in payload.get("tasks") or [] if isinstance(t, dict)]
        history = await _attach_practice_status(snapshot.user_id, snapshot.path_id, tasks)

        print(f"user={snapshot.user_id} path={snapshot.path_id} milestone={snapshot.milestone} "
              f"source={snapshot.source}")
        for task in tasks:
            print(f"    {task.get('id'):<34} {task.get('practice_status_label') or '—'}")
        if history:
            print("    历史实践：")
            for item in history:
                print(f"      [{item['status_label']}] {item['task_key']}  {item['task_title']}")
        else:
            print("    历史实践：（无）")
        print()

    await Tortoise.close_connections()


asyncio.run(main())

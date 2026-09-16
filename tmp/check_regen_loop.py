"""Read-only: which bound node resources would be rejected at reuse time (=> regenerate)?

Mirrors backend/src/service/path/helpers.py:138-192 exactly. SELECTs only.
Run: /f/anaconda3/envs/zhiban/python.exe tmp/check_regen_loop.py
"""
import asyncio
import json
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
    ]
}

REQUESTED = ["document", "ppt", "mindmap"]


async def main() -> None:
    await Tortoise.init(db_url=os.environ["database"], modules=MODULES)

    from backend.src.ai_core.ppt_planner import PPT_MAX_PAGES_PER_DECK
    from backend.src.models.path_model import PathNode, UserPathProgress
    from backend.src.models.resource_model import GeneratedResource
    from backend.src.service.path.helpers import _resource_page_count
    from backend.src.service.path.teaching_context import build_node_teaching_context
    from backend.src.service.resource.document_quality import validate_document_chapter
    from backend.src.service.resource.persistence import is_failed_generation_content

    rows = await UserPathProgress.all().values("user_id", "path_id", "node_id", "resource_ids")
    bound_rows = [r for r in rows if (r.get("resource_ids") or "").strip() not in ("", "[]", "null")]
    print(f"user_path_progress 总行数        = {len(rows)}")
    print(f"其中已绑定资源(resource_ids 非空) = {len(bound_rows)}")
    print()

    at_risk = []
    for row in bound_rows:
        user_id, path_id, node_id = row["user_id"], row["path_id"], row["node_id"]
        try:
            bound_ids = json.loads(row["resource_ids"] or "[]")
        except (TypeError, ValueError):
            continue
        if not bound_ids:
            continue

        node = await PathNode.filter(id=node_id, path_id=path_id).first()
        if node is None:
            continue
        ctx = await build_node_teaching_context(path_id, node_id, user_id)
        topic = node.topic

        records = [
            r
            for r in await GeneratedResource.filter(id__in=bound_ids, user_id=user_id).all()
        ]
        by_id = {r.id: r for r in records}
        ordered = [by_id[rid] for rid in bound_ids if rid in by_id]

        seen_types: set[str] = set()
        rejected: dict[str, list[str]] = {}
        for record in ordered:
            rtype = str(record.resource_type or "").strip()
            reasons: list[str] = []
            if rtype in REQUESTED:
                if topic and str(record.topic or "").strip() != topic:
                    reasons.append("topic 不一致")
                if is_failed_generation_content(record.content):
                    reasons.append("failed content")
                if rtype == "document" and ctx is not None:
                    reasons.extend(validate_document_chapter(record.content, ctx))
                if rtype == "ppt" and _resource_page_count(record.content) > PPT_MAX_PAGES_PER_DECK:
                    reasons.append("PPT 超页数")
            if reasons:
                rejected[rtype] = reasons
            else:
                seen_types.add(rtype)

        missing = [t for t in REQUESTED if t not in seen_types]
        gen_types = [t for t in missing if t != "exercise"]
        if gen_types:
            at_risk.append((user_id, path_id, node_id, topic, gen_types, rejected))

    print(f"下次访问会真正触发重新生成的节点 = {len(at_risk)}")
    print()
    for user_id, path_id, node_id, topic, gen_types, rejected in at_risk:
        kp = (rejected.get("document") or ["?"])[0]
        print(f"  u{user_id} path{path_id} node{node_id} -> 重新生成 {gen_types}")
        print(f"      topic: {topic}")
        print(f"      拒收原因: {rejected}")

    await Tortoise.close_connections()


asyncio.run(main())

import asyncio
import os

from dotenv import load_dotenv
from tortoise import Tortoise

# database.py 可能在 main.py 加载 .env 之前被其他模块导入，因此这里必须
# 自己加载项目配置。生产和开发环境统一使用已配置的 MySQL，不再回退到 SQLite。
_backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
load_dotenv(os.path.join(_backend_root, ".env"))
database = os.getenv("database", "").strip()
if not database:
    raise RuntimeError("未配置 database，必须在 backend/.env 或环境变量中提供 MySQL 连接串")
# 连接池参数：默认最小5、最大20
if "mysql://" in database and "minsize" not in database:
    sep = "&" if "?" in database else "?"
    database = f"{database}{sep}minsize=5&maxsize=20"

#幂等初始化连接数据库，防止数据库重复连接
_DB_INITIALIZED = False
_DB_INIT_LOCK = asyncio.Lock()

async def _ensure_generated_resource_visibility_column():
    import logging
    _log = logging.getLogger(__name__)
    conn = Tortoise.get_connection("default")
    for sql in [
        "ALTER TABLE generated_resources ADD COLUMN visibility VARCHAR(10) NOT NULL DEFAULT 'private'",
        "ALTER TABLE generated_images ADD COLUMN visibility VARCHAR(10) NOT NULL DEFAULT 'private'",
        "ALTER TABLE chat_history ADD COLUMN agent_id INT NULL",
        "ALTER TABLE user_agents ADD COLUMN is_system INT NOT NULL DEFAULT 0",
        # 学习路径服务于个体用户：存量数据统一置为私有
        "UPDATE learning_paths SET is_public = 0 WHERE is_public = 1",
    ]:
        try:
            await conn.execute_query(sql)
        except Exception:
            _log.debug("ALTER TABLE 跳过（列可能已存在）: %s", sql[:60])

async def _ensure_classroom_lesson_schema():
    """Keep the current classroom snapshot table aligned with the lesson protocol."""
    import logging
    _log = logging.getLogger(__name__)
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query(
            "ALTER TABLE classroom_lessons MODIFY COLUMN schema_version "
            "VARCHAR(24) NOT NULL DEFAULT 'exercise-v2' COMMENT '课堂协议版本'"
        )
    except Exception:
        # SQLite and already-compatible MySQL schemas both land here harmlessly.
        _log.debug("课堂表协议版本迁移跳过", exc_info=True)


async def _ensure_path_node_teaching_spec_column():
    """Backfill the additive teaching contract column for existing MySQL tables."""
    import logging

    _log = logging.getLogger(__name__)
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query(
            "ALTER TABLE path_nodes ADD COLUMN teaching_spec TEXT NULL "
            "COMMENT '节点教学规格 JSON'"
        )
    except Exception as exc:
        error_text = str(exc).lower()
        is_duplicate_column = "1060" in error_text or "duplicate column" in error_text
        if is_duplicate_column:
            _log.debug("路径节点教学规格字段已存在")
            return
        _log.exception("路径节点教学规格字段迁移失败")
        raise


async def _ensure_path_node_difficulty_score_column():
    """为存量路径补充可空难度分数；旧节点由概览服务按元数据兜底计算。"""
    import logging

    _log = logging.getLogger(__name__)
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query(
            "ALTER TABLE path_nodes ADD COLUMN difficulty_score DOUBLE NULL "
            "COMMENT '节点相对难度倍数，首节点为 1.0'"
        )
    except Exception as exc:
        error_text = str(exc).lower()
        is_duplicate_column = "1060" in error_text or "duplicate column" in error_text
        if is_duplicate_column:
            try:
                await conn.execute_query(
                    "ALTER TABLE path_nodes MODIFY COLUMN difficulty_score DOUBLE NULL "
                    "COMMENT '节点相对难度倍数，首节点为 1.0'"
                )
            except Exception:
                _log.debug("路径节点难度字段类型迁移跳过", exc_info=True)
            return
        _log.exception("路径节点难度字段迁移失败")
        raise

async def init_db():
    global _DB_INITIALIZED
    if _DB_INITIALIZED :
        return 
    async with _DB_INIT_LOCK:
        if _DB_INITIALIZED:
            return
        await Tortoise.init(
            db_url=database,
            modules={"models": ["backend.src.models.usermodel", "backend.src.models.chat_history_model", "backend.src.models.portraitmodel", "backend.src.models.portrait_radar_model", "backend.src.models.knowledgemodel", "backend.src.models.resource_model", "backend.src.models.agent_skill_model", "backend.src.models.image_model", "backend.src.models.exam_model", "backend.src.models.path_model", "backend.src.models.advanced_task_model", "backend.src.models.advanced_practice_model", "backend.src.models.narration_model", "backend.src.models.study_model", "backend.src.models.study_room_model", "backend.src.models.mock_classroom_model", "backend.src.models.video_model", "backend.src.models.task_model", "backend.src.models.email_code_model", "backend.src.models.notification_model", "backend.src.models.curriculum_model", "backend.src.models.annotation_model", "backend.src.models.user_agent_model", "backend.src.models.memory_kv_model", "backend.src.models.memory_episode_model", "backend.src.models.memory_message_model", "backend.src.models.memory_summary_model", "backend.src.models.classroom_model"]}
        )
        await Tortoise.generate_schemas()
        await _ensure_generated_resource_visibility_column()
        await _ensure_classroom_lesson_schema()
        await _ensure_path_node_teaching_spec_column()
        await _ensure_path_node_difficulty_score_column()
        _DB_INITIALIZED = True

async def close_db():
    await Tortoise.close_connections()

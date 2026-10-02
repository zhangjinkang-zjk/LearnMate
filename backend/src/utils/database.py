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

async def _ensure_embedding_model_column():
    """给三张存向量的表补 embedding_model 列。

    向量与生成它的嵌入模型强绑定。记录 model_id 后，"库里存的向量是哪个模型生成的"
    就能精确判断 —— 否则换模型只能靠向量长度去猜，两个模型维度相同时根本区分不出来。
    存量行留 NULL，由 reembed 脚本回填。
    """
    import logging

    _log = logging.getLogger(__name__)
    conn = Tortoise.get_connection("default")
    for table in ("knowledge_vectors", "memory_episode", "memory_message_vector"):
        try:
            await conn.execute_query(
                f"ALTER TABLE {table} ADD COLUMN embedding_model VARCHAR(64) NULL "
                f"COMMENT '生成该向量的嵌入模型 id'"
            )
        except Exception:
            _log.debug("ALTER TABLE 跳过（列可能已存在）: %s.embedding_model", table)


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


async def _ensure_user_agent_key_column():
    """为存量库补上"内置领域智能体标识"这一列。

    没有这一列之前，判别"这条系统行是哪个领域"只能靠 `is_system=True` —— 那时一个用户
    身上只有一条系统行，取唯一的那个没问题。多一个领域就不成立了：`first()` 取到哪条是
    随机的，等于把学幼师的学生接给写代码的教练。存量行留 NULL（它们都是开发教练那一份，
    首次按 key 取时会认领，见 `classroom_chat._claim_legacy_row`）。
    """
    import logging

    _log = logging.getLogger(__name__)
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query(
            "ALTER TABLE user_agents ADD COLUMN agent_key VARCHAR(32) NULL "
            "COMMENT '内置领域智能体标识；用户自建的为 NULL'"
        )
    except Exception as exc:
        error_text = str(exc).lower()
        is_duplicate_column = "1060" in error_text or "duplicate column" in error_text
        if is_duplicate_column:
            _log.debug("智能体标识字段已存在")
            return
        _log.exception("智能体标识字段迁移失败")
        raise


async def _drop_advanced_practice_phase_columns():
    """清掉进阶实践会话上阶段机留下的五列。

    这五列（`current_phase` / `completed_phases` / `deliverable_state` /
    `final_submission` / `evaluation`）是阶段机与判分的存储，**从来没有被任何代码
    读写过**，删掉不丢任何信息。

    **为什么必须在这里删，而不是"顺手从模型上拿掉就行"**：`generate_schemas()` 只建
    缺失的**表**，不删多余的**列**。存量库里那五列还在，而 `completed_phases` 是
    `NOT NULL` 且没有默认值（MySQL 的 JSON 列本来就给不了默认值）—— 模型不再声明它、
    列又还在，INSERT 会撞 MySQL 1364 把「打开实践会话」直接打成 500。所以删列这件事
    必须发生在服务开始接请求之前，也就是这个函数里。

    逐列一条 `ALTER`，而不是一条多列的语句：库里可能处在"删了一半"的状态（比如只被
    早期版本补过 `deliverable_state` 的库），多列语句缺一列就整体失败，逐列则各删各的。
    1091（列不存在）和 1146（表不存在）是**正常**结果 —— 新库由 `generate_schemas()`
    按模型直接建出来，这里本就该什么都不做。其余异常原样抛出：连不上库、没权限这类
    问题要在**启动时**看见，不能拖成运行期一条莫名其妙的 INSERT 报错。

    等所有环境都跑过一遍之后，这个函数和 `init_db()` 里的那次调用可以一起删掉。
    """
    import logging

    _log = logging.getLogger(__name__)
    conn = Tortoise.get_connection("default")
    dropped: list[str] = []
    for column in (
        "current_phase",
        "completed_phases",
        "deliverable_state",
        "final_submission",
        "evaluation",
    ):
        try:
            await conn.execute_query(f"ALTER TABLE advanced_practice_sessions DROP COLUMN {column}")
            dropped.append(column)
        except Exception as exc:
            error_text = str(exc).lower()
            is_missing = (
                "1091" in error_text
                or "1146" in error_text
                or "check that column" in error_text
                or "doesn't exist" in error_text
            )
            if is_missing:
                continue
            _log.exception("进阶实践阶段遗留列清理失败（列名 %s）", column)
            raise
    if dropped:
        _log.warning("进阶实践会话的阶段遗留列已清除：%s", "、".join(dropped))


async def _ensure_curriculum_by_direction_table():
    """课程缓存表从「专业×年级」改成「按学习方向」—— 结构对不上就整张重建。

    `generate_schemas()` 只建缺失的**表**，不会改已存在的表。所以模型上把
    `major` + `grade` 换成 `direction` 之后，没跑迁移的库会一直带着旧结构，方向拆解
    一查就撞 MySQL 1054 `Unknown column 'direction'`，把 `/path/generate-from-direction`
    直接打成 500。

    为什么这里敢 DROP：这张表是**纯派生缓存** —— 内容是模型按方向现生成再写回来的，
    随时可以重建；而它的旧形态（专业×年级）从来没有被调用过（`sys_user.major`/`grade`
    一直是 NULL，表里一行都没有）。丢掉的只有"下次多花一次模型调用"。

    只在"确实缺 direction 列"或"表不存在"时重建：其他异常（连不上库等）原样抛出去，
    不能因为一个连不通就把表删了。
    """
    import logging

    _log = logging.getLogger(__name__)
    conn = Tortoise.get_connection("default")
    try:
        await conn.execute_query("SELECT direction FROM curriculum_courses LIMIT 1")
        return
    except Exception as exc:
        error_text = str(exc)
        # 1054 = Unknown column（旧结构），1146 = Table doesn't exist（新库，交给
        # generate_schemas 建即可，这里不用管）
        if "1054" not in error_text and "1146" not in error_text:
            _log.exception("课程缓存表结构检查失败（不是结构问题，不重建）")
            raise
        if "1146" in error_text:
            return

    try:
        await conn.execute_query("DROP TABLE IF EXISTS curriculum_courses")
        # 上面那次 generate_schemas() 已经跑过了，删完要再跑一次才会按新模型建出来。
        await Tortoise.generate_schemas()
        _log.warning("课程缓存表结构已过期（缺 direction 列），已按「学习方向」重建")
    except Exception:
        _log.exception("课程缓存表重建失败")
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
            modules={"models": ["backend.src.models.usermodel", "backend.src.models.chat_history_model", "backend.src.models.portraitmodel", "backend.src.models.portrait_radar_model", "backend.src.models.knowledgemodel", "backend.src.models.resource_model", "backend.src.models.agent_skill_model", "backend.src.models.image_model", "backend.src.models.exam_model", "backend.src.models.path_model", "backend.src.models.advanced_task_model", "backend.src.models.advanced_practice_model", "backend.src.models.narration_model", "backend.src.models.study_model", "backend.src.models.video_model", "backend.src.models.task_model", "backend.src.models.email_code_model", "backend.src.models.notification_model", "backend.src.models.curriculum_model", "backend.src.models.annotation_model", "backend.src.models.user_agent_model", "backend.src.models.memory_kv_model", "backend.src.models.memory_episode_model", "backend.src.models.memory_message_model", "backend.src.models.memory_summary_model", "backend.src.models.classroom_model"]}
        )
        await Tortoise.generate_schemas()
        await _ensure_generated_resource_visibility_column()
        await _ensure_embedding_model_column()
        await _ensure_classroom_lesson_schema()
        await _ensure_path_node_teaching_spec_column()
        await _ensure_path_node_difficulty_score_column()
        await _ensure_user_agent_key_column()
        await _drop_advanced_practice_phase_columns()
        await _ensure_curriculum_by_direction_table()
        _DB_INITIALIZED = True

async def close_db():
    await Tortoise.close_connections()

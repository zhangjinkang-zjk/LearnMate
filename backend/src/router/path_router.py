"""学习路径路由"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Depends, Body
from starlette.responses import StreamingResponse

from backend.src.service.path.service import PathService
from backend.src.service.path.classroom import generate_classroom_audio, generate_classroom_lesson, get_saved_classroom_lesson
from backend.src.service.path.classroom_transition import get_classroom_transition
from backend.src.service.path.classroom_chat import stream_classroom_chat
from backend.src.utils.jwt import get_user_id_from_token
from backend.src.schemas.path import (
    GeneratePathRequest,
    EnrollPathRequest,
    SubmitNodeQuizRequest,
    RegeneratePathRequest,
    GenerateFromProfileRequest,
    GenerateFromDirectionRequest,
    GenerateClassroomRequest,
    ClassroomNarrationRequest,
    ClassroomChatRequest,
    GenerateNodeResourcesRequest,
)

router = APIRouter(prefix="/path", tags=["学习路径"])
logger = logging.getLogger(__name__)
# 每个用户**正在跑的全部**后台路径生成任务（不是"最近一条"）：只留最近一条的话，被挤掉
# 的那条就没有强引用了 —— asyncio 对任务只持弱引用，它会被垃圾回收，跑到一半消失。
_BACKGROUND_PATH_TASKS: dict[int, set[asyncio.Task]] = {}

# 学生确认画像之后**同步等待**的那一条路径，节点数封顶到这个数。
#
# 等待时间几乎全在模型调用上：每 4 个节点一组、一组一次调用（`_GROUP_SIZE`），而一次调用
# 光首字延迟就是二十几到三十几秒。节点数从 20 降到 12 就是 5 组变 3 组、少一整波。实测
# 20 个节点的首条路径要 5 分钟上下 —— 正好压在前端那 5 分钟超时上，于是"迟迟进不去、
# 还超时"。封顶之后这条路径落在正常长度（_compute_node_count 给的是 8-30）的低段，够用，
# 其余科目仍按各自应有的长度在后台生成。
_ENTRY_PATH_NODE_CAP = 12


def _entry_node_count(node_cap: int, requested: int) -> int:
    """入口路径实际用几个节点。

    封顶只**往下压**，不往上抬：调用方明确要得更少（比如 6）就照他说的，别拿上限把
    他要的长度顶回去。node_cap 为 0 表示这条路径不在同步等待里（后台生成），照原样。
    """
    if node_cap <= 0:
        return requested
    if requested <= 0:
        return node_cap
    return min(node_cap, requested)


def _track_background_path_task(user_id: int, task: asyncio.Task) -> None:
    """保留后台任务引用并统一记录异常，避免任务被回收或静默失败。

    **不取消上一条，而且新的这条也必须登记。** 这两件事原来都是反的：

    - 上一条跑的是同一批"其余科目"，取消它等于把已经跑了几分钟的东西整条扔掉 ——
      一条路径要跑完整张 graph（Leader 实测 105-185 秒）才落库，中途被杀不留任何痕迹。
      两条并联最坏是同一科目算两遍，而 `generate_path` 自己对已存在的科目会复用
      （撞 unique 约束也会退化成复用），代价远小于"一条都没有"。
    - 原来"取消旧的然后 return"，新的这条就没进 `_BACKGROUND_PATH_TASKS`，而 asyncio 对
      任务只持弱引用 —— 连点两次或超时重试一次，**两条尾巴一起消失**，用户永远只有一条
      路径。所以这里是 `setdefault`，同一用户的在跑任务都留着强引用。
    """
    inflight = _BACKGROUND_PATH_TASKS.setdefault(user_id, set())
    if any(not item.done() for item in inflight):
        logger.info(
            "上一条后台路径生成还在跑，这次并联而不是取消 user_id=%s 在跑=%d",
            user_id,
            sum(1 for item in inflight if not item.done()),
        )
    inflight.add(task)

    def _finish(completed: asyncio.Task) -> None:
        current = _BACKGROUND_PATH_TASKS.get(user_id)
        if current is not None:
            current.discard(completed)
            if not current:
                _BACKGROUND_PATH_TASKS.pop(user_id, None)
        if completed.cancelled():
            return
        error = completed.exception()
        if error:
            logger.error(
                "后台学习路径生成任务异常: %s",
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(_finish)


async def _assert_path_access(path_id: int, user_id: int, *, public_readable: bool = False) -> None:
    """校验用户对该路径的访问权：创建者始终放行；公共路径可读；
    其余读写一律要求已加入（enroll）。未通过统一抛 404，不暴露路径存在性。"""
    from backend.src.models.path_model import LearningPath, UserPathProgress

    path = await LearningPath.filter(id=path_id).only("id", "user_id", "is_public").first()
    if not path:
        raise HTTPException(status_code=404, detail="路径不存在")
    if path.user_id == user_id:
        return
    if public_readable and path.is_public:
        return
    if await UserPathProgress.filter(user_id=user_id, path_id=path_id).exists():
        return
    raise HTTPException(status_code=404, detail="路径不存在")


@router.post("/generate")
async def generate_path(data: GeneratePathRequest, user_id: int = Depends(get_user_id_from_token)):
    """AI 生成学习路径"""
    result = await PathService.generate_path(data.subject, user_id, data.difficulty, data.node_count, data.force_regenerate)
    return {"code": 200, "msg": "success", "data": result}


@router.post("/generate/stream")
async def generate_path_stream(data: GeneratePathRequest, user_id: int = Depends(get_user_id_from_token)):
    return StreamingResponse(
        PathService.generate_path_stream(data.subject, user_id, data.difficulty, data.node_count),
        media_type="text/event-stream",
    )


@router.post("/generate-from-direction")
async def generate_paths_from_direction(data: GenerateFromDirectionRequest, user_id: int = Depends(get_user_id_from_token)):
    """拆解学习方向，先生成一条可进入的路径，其余路径在后台继续生成。"""
    from backend.src.service.curriculum.service import sync_direction_subjects
    from backend.src.service.portrait.service import is_usable_direction
    direction = data.direction.strip()
    goal = data.goal.strip()
    # "有值"不等于"有方向"：学生第 1 问答「不知道」时，这个字符串以前会被当成方向收下，
    # 然后拆出一整套跟他的方向毫无关系的科目（"用来当副业挣钱" → 一整套营销课）。
    # 拿不到能用的方向就回落到画像里存的那一份，两边都没有就明确让他回去补一个。
    if not is_usable_direction(direction):
        from backend.src.models.usermodel import User
        from backend.src.service.portrait.service import parse_traits
        user = await User.filter(id=user_id).first()
        picture = await user.picture if user else None
        onboarding = parse_traits(picture.traits if picture else None).get("onboarding") or {}
        stored = str(onboarding.get("direction") or "").strip()
        direction = stored if is_usable_direction(stored) else ""
        goal = goal or str(onboarding.get("goal") or "").strip()
    if not direction:
        raise HTTPException(status_code=400, detail="还没有确定的学习方向，请先完成学习访谈或补填一个方向")
    subjects = await sync_direction_subjects(
        user_id,
        direction,
        goal,
        data.subject_limit,
        force_regenerate=data.force_regenerate,
    )
    from backend.src.models.path_model import LearningPath

    async def generate_or_reuse(subject: str, node_cap: int = 0):
        # node_cap 只给"学生正在同步等待的那一条"用：等待时间主要由节点数决定（每 4 个节点
        # 一组、一组一次模型调用，一次调用首字就是二十几到三十几秒）。入口这条封顶之后，
        # 其余科目仍按各自的正常长度在后台生成，学生不必站在这里等。
        node_count = _entry_node_count(node_cap, data.node_count)
        if data.force_regenerate:
            existing = await LearningPath.filter(user_id=user_id, subject=subject).first()
            if existing:
                result = await PathService.regenerate_path(existing.id, user_id)
            else:
                result = await PathService.generate_path(subject, user_id, data.difficulty, node_count)
        else:
            result = await PathService.generate_path(subject, user_id, data.difficulty, node_count)

        # 生成接口也负责把路径接入当前学习进度。新路径在 generate_path
        # 内已经完成初始化；缓存路径则需要在这里补齐，否则概览接口无法读取。
        path_id = result.get("path_id") if isinstance(result, dict) else None
        if path_id and result.get("cached"):
            await PathService.enroll_path(path_id, user_id)
        return result

    first_result = None
    first_subject_index = -1
    failed_subjects = []
    # 按课程架构师返回的依赖顺序尝试，确保至少有一条路径可进入学习空间。
    for index, subject in enumerate(subjects):
        try:
            first_result = await generate_or_reuse(subject, _ENTRY_PATH_NODE_CAP)
            first_subject_index = index
            break
        except Exception as error:
            failed_subjects.append(subject)
            logger.exception("首条学习路径生成失败 subject=%s user_id=%s", subject, user_id)

    if first_result is None:
        raise HTTPException(
            status_code=503,
            detail="暂时无法生成学习路径，请稍后重试",
        )

    def serialize_path(subject: str, result: dict) -> dict:
        return {
            "subject": subject,
            "status": "regenerated" if result.get("regenerated") else ("cached" if result.get("cached") else "created"),
            "path_id": result.get("path_id"),
            "node_count": result.get("node_count", len(result.get("nodes", []))),
        }

    paths = [serialize_path(subjects[first_subject_index], first_result)]
    remaining_subjects = subjects[first_subject_index + 1:] + failed_subjects

    async def generate_remaining_paths() -> None:
        # 后台按顺序生成，避免首次进入时并发触发多组 LLM/数据库写入。
        for subject in remaining_subjects:
            try:
                result = await generate_or_reuse(subject)
                logger.info(
                    "后台学习路径已生成 user_id=%s subject=%s path_id=%s",
                    user_id,
                    subject,
                    result.get("path_id"),
                )
            except Exception:
                logger.exception("后台学习路径生成失败 subject=%s user_id=%s", subject, user_id)

    if remaining_subjects:
        _track_background_path_task(user_id, asyncio.create_task(generate_remaining_paths()))

    return {
        "code": 200,
        "msg": "首条学习路径已就绪，其余路径正在后台生成",
        "data": {
            "direction": direction,
            "subjects": subjects,
            "paths": paths,
            "pending_subjects": remaining_subjects,
            "generation_status": "partial" if remaining_subjects else "complete",
        },
    }


@router.get("/list")
async def list_paths(user_id: int = Depends(get_user_id_from_token)):
    """路径列表"""
    result = await PathService.list_paths(user_id)
    return {"code": 200, "msg": "success", "data": result}


@router.get("/{path_id}")
async def get_path(path_id: int, user_id: int = Depends(get_user_id_from_token)):
    """路径详情（含所有节点）"""
    result = await PathService.get_path(path_id, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="路径不存在")
    return {"code": 200, "msg": "success", "data": result}


@router.post("/enroll")
async def enroll_path(data: EnrollPathRequest, user_id: int = Depends(get_user_id_from_token)):
    """加入路径开始学习"""
    try:
        result = await PathService.enroll_path(data.path_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"code": 200, "msg": "success", "data": result}


@router.get("/{path_id}/progress")
async def get_progress(path_id: int, user_id: int = Depends(get_user_id_from_token)):
    """用户在路径上的整体进度"""
    await _assert_path_access(path_id, user_id)
    result = await PathService.get_progress(path_id, user_id)
    return {"code": 200, "msg": "success", "data": result}


@router.get("/{path_id}/node/{node_id}")
async def get_node(path_id: int, node_id: int, user_id: int = Depends(get_user_id_from_token)):
    """节点详情（含资源和进度）"""
    await _assert_path_access(path_id, user_id)
    result = await PathService.get_node(path_id, node_id, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"code": 200, "msg": "success", "data": result}


@router.post("/{path_id}/node/{node_id}/generate-resources")
async def generate_node_resources(path_id: int, node_id: int, user_id: int = Depends(get_user_id_from_token)):
    """手动为节点生成学习资源"""
    await _assert_path_access(path_id, user_id)
    try:
        result = await PathService.generate_node_resources(path_id, node_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"code": 200, "msg": "success", "data": result}


@router.post("/{path_id}/node/{node_id}/generate-quiz")
async def generate_node_quiz(
    path_id: int,
    node_id: int,
    force_regenerate: bool = Body(default=False, embed=True),
    user_id: int = Depends(get_user_id_from_token),
):
    """为节点生成测验题目"""
    await _assert_path_access(path_id, user_id)
    try:
        result = await PathService.generate_node_quiz(
            path_id,
            node_id,
            user_id,
            pre_generate=True,
            force_regenerate=force_regenerate,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"code": 200, "msg": "success", "data": result}


@router.post("/{path_id}/node/{node_id}/classroom")
async def generate_node_classroom(
    path_id: int,
    node_id: int,
    data: GenerateClassroomRequest,
    user_id: int = Depends(get_user_id_from_token),
):
    """为路径节点生成互动课堂脚本"""
    await _assert_path_access(path_id, user_id)
    result = await generate_classroom_lesson(
        path_id,
        node_id,
        user_id,
        {"node": data.node, "resources": data.resources, "quiz": data.quiz, "force_regenerate": data.force_regenerate},
    )
    if not result:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"code": 200, "msg": "success", "data": result}


@router.get("/{path_id}/node/{node_id}/classroom")
async def get_node_classroom(path_id: int, node_id: int, user_id: int = Depends(get_user_id_from_token)):
    """Read a complete saved classroom; missing or incomplete records return null data."""
    await _assert_path_access(path_id, user_id)
    result = await get_saved_classroom_lesson(path_id, node_id, user_id)
    return {"code": 200, "msg": "success", "data": result}


@router.get("/{path_id}/node/{node_id}/classroom-transition")
async def get_node_classroom_transition(path_id: int, node_id: int, user_id: int = Depends(get_user_id_from_token)):
    """课堂生成时的非阻塞过渡内容，不调用课堂智能体。"""
    await _assert_path_access(path_id, user_id)
    result = await get_classroom_transition(path_id, node_id, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"code": 200, "msg": "success", "data": result}


@router.post("/classroom/narrate")
async def narrate_classroom(data: ClassroomNarrationRequest, user_id: int = Depends(get_user_id_from_token)):
    """生成互动课堂 LearnMate 旁白音频"""
    try:
        result = await generate_classroom_audio(data.text, user_id, data.voice, data.rate)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"code": 200, "msg": "success", "data": result}


@router.post("/classroom/chat")
async def classroom_chat(data: ClassroomChatRequest, user_id: int = Depends(get_user_id_from_token)):
    """互动课堂对话（流式）：保存课堂专属历史并参与画像、记忆更新。"""
    await _assert_path_access(data.path_id, user_id)
    return StreamingResponse(
        stream_classroom_chat(
            user_id=user_id,
            path_id=data.path_id,
            node_id=data.node_id,
            resource_id=data.resource_id,
            segment=data.segment,
            scenario=data.scenario,
            text=data.text,
            practice_session_id=data.practice_session_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{path_id}/node/{node_id}/generate-resources/stream")
async def generate_node_resources_stream(
    path_id: int,
    node_id: int,
    data: GenerateNodeResourcesRequest | None = Body(default=None),
    user_id: int = Depends(get_user_id_from_token),
):
    """流式为节点生成学习资源（SSE），生成好一个推送一个"""
    await _assert_path_access(path_id, user_id)
    logger.info(
        "节点资源确保请求 path_id=%s node_id=%s user_id=%s resource_types=%s background=%s",
        path_id,
        node_id,
        user_id,
        data.resource_types if data else None,
        data.background if data else False,
    )
    return StreamingResponse(
        PathService.generate_node_resources_stream(
            path_id, node_id, user_id,
            resource_types=data.resource_types if data else None,
            llm_priority="low" if data and data.background else "high",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{path_id}/node/{node_id}/generate-quiz/stream")
async def generate_node_quiz_stream(path_id: int, node_id: int, user_id: int = Depends(get_user_id_from_token)):
    """流式为节点生成测验题目（SSE）"""
    await _assert_path_access(path_id, user_id)
    return StreamingResponse(
        PathService.generate_node_quiz_stream(path_id, node_id, user_id),
        media_type="text/event-stream",
    )


@router.post("/{path_id}/node/{node_id}/submit-quiz")
async def submit_node_quiz(
    path_id: int,
    node_id: int,
    data: SubmitNodeQuizRequest,
    user_id: int = Depends(get_user_id_from_token),
):
    """提交节点测验 → 评分 → 门禁 → 解锁下一节点"""
    await _assert_path_access(path_id, user_id)
    try:
        result = await PathService.submit_node_quiz(
            path_id,
            node_id,
            user_id,
            data.session_id,
            answers=data.answers,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"code": 200, "msg": "success", "data": result}


@router.post("/{path_id}/video")
async def generate_path_video(path_id: int, user_id: int = Depends(get_user_id_from_token)):
    """启动（或接入）路径视频生成，立即返回状态。

    生成要跑几分钟，不能再让请求同步等它——那样必然撞上前端超时，而后端继续跑完，
    用户看到的就是"报错但后端还在忙"。现在返回 status，由前端轮询 GET 取结果；
    生成失败也不再是 500，而是 status="failed" + error，前端才读得到原因。
    """
    await _assert_path_access(path_id, user_id)
    try:
        result = await PathService.start_path_video(path_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"code": 200, "msg": "success", "data": result}


@router.get("/{path_id}/video")
async def get_path_video(path_id: int, user_id: int = Depends(get_user_id_from_token)):
    """获取路径视频的当前状态（前端轮询目标）"""
    await _assert_path_access(path_id, user_id)
    result = await PathService.get_path_video(path_id, user_id)
    return {"code": 200, "msg": "success", "data": result}


@router.post("/regenerate")
async def regenerate_path(data: RegeneratePathRequest, user_id: int = Depends(get_user_id_from_token)):
    """基于最新画像重建路径"""
    await _assert_path_access(data.path_id, user_id)
    try:
        result = await PathService.regenerate_path(data.path_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"code": 200, "msg": "success", "data": result}


@router.post("/generate-from-profile")
async def generate_paths_from_profile(data: GenerateFromProfileRequest, user_id: int = Depends(get_user_id_from_token)):
    """根据用户专业 + 年级自动获取课程 → 批量生成学习路径（1h 内不重复）"""
    from datetime import datetime, timedelta
    from backend.src.models.usermodel import User
    from backend.src.models.path_model import LearningPath
    from backend.src.service.curriculum.service import get_courses
    from backend.src.models.notification_model import Notification

    user = await User.filter(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not user.major:
        raise HTTPException(status_code=400, detail="请先在个人资料中设置专业")

    # 时间窗口防抖
    recent = await LearningPath.filter(
        user_id=user_id,
        created_at__gte=datetime.now() - timedelta(hours=1),
    ).first()
    if recent:
        return {"code": 200, "msg": "1小时内已生成过路径，请稍后再试", "data": {"major": user.major, "grade": user.grade, "courses": [], "paths": []}}

    courses = await get_courses(user.major)
    courses = courses[:max(1, data.course_limit)]

    import asyncio
    results = await asyncio.gather(
        *[PathService.generate_path(course, user_id, data.difficulty, data.node_count) for course in courses],
        return_exceptions=True,
    )

    new_paths = []
    cached_count = 0
    for course, result in zip(courses, results):
        if isinstance(result, Exception):
            continue
        if result.get("cached"):
            cached_count += 1
        else:
            new_paths.append({"path_id": result.get("path_id"), "subject": course, "nodes": result.get("nodes", [])})

    all_subjects = [p.get("subject") for p in new_paths]
    if new_paths:
        course_names = "、".join(all_subjects)
        grade_text = f"{user.grade}" if user.grade else ""
        suffix = f"（另外 {cached_count} 门已存在，已跳过）" if cached_count else ""
        await Notification.create(
            type="system",
            title="学习路径已生成",
            content=f"已根据{grade_text}{user.major}的课程（{course_names}）生成 {len(new_paths)} 条学习路径。{suffix}",
            target_url=f"/learning-path?major={user.major}",
            target_user_id=user_id,
        )

    return {
        "code": 200,
        "msg": "success",
        "data": {
            "major": user.major,
            "grade": user.grade,
            "courses": all_subjects,
            "paths": new_paths,
        },
    }

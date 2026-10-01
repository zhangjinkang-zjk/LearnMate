# -*- coding: utf-8 -*-
"""确认画像之后那条路径：接口不许同步等，等待交给轮询。

症状：点完"确认画像"迟迟进不去学习概览，而且超时。原因是生成一条路径要串 6-10 次模型调用，
每次光首字延迟就二十几到三十几秒：

    方向→科目 1 次 + Leader 1 次（实测 105-185 秒）+ Executor 每 4 个节点一组
    + Reviewer 1 次（把整条路径的 JSON 塞进一个 prompt）

前端那次请求给的是 5 分钟（`learningApi.generatePathsFromDirection`），正好压在这条路的中间，
所以有时进得去、有时超时。**而客户端放弃等待不等于服务端停了** —— 它会把路径写完再落库，
于是"重试一次"变成再生成一遍，等待翻倍。

现在分两层止血：

1. **接口不再同步等**：`POST /path/generate-from-direction` 拆完科目就返回（几百毫秒），
   整批生成丢给后台，前端改成轮询 `/path/list` 问"到了没有"。
2. **两条入口共用一把用户级锁**：诊断收尾和「确认画像」相隔只有几十秒，都会要同一批科目；
   没有锁就是同一次生成做两遍（见 `path_generation_lock`）。

还有一件老账：Executor 的并行度（2 路 → 4 路），以及入口那条路径的节点封顶。

注意 `ENTRY_PATH_NODE_CAP` 现在在 `path/service.py`，不在 router —— 两条入口都要用它。
"""

import asyncio

import pytest

from backend.src.ai_core import path_graph
from backend.src.ai_core import llm_config
from backend.src.router import path_router
from backend.src.schemas.path import GenerateFromDirectionRequest
from backend.src.service.path import service as path_service


def test_the_executor_runs_more_than_two_groups_at_a_time():
    """20 个节点分 5 组：2 路并行是 3 波，4 路是 2 波 —— 一波就是一次模型往返。"""
    assert path_graph._MAX_GROUP_CONCURRENCY == 4


def test_the_group_concurrency_fits_the_per_user_pool():
    """一批路径生成要能把并发池用满，又不能反过来被自己人卡住。

    同一个用户的整批生成现在是串行的（`path_generation_lock`），所以这 4 路全归当前
    这一条路径 —— 超了每用户 path 池的话，学生等的就是信号量上的排队时间。
    """
    budget = llm_config._PER_USER["path"]
    assert path_graph._MAX_GROUP_CONCURRENCY <= budget, (
        f"并发度 {path_graph._MAX_GROUP_CONCURRENCY} 超过每用户 path 池的 {budget}"
    )


def test_the_group_size_still_packs_four_nodes_per_call():
    """每组的节点数没变（改的是同时跑几组）—— 这条只是防止顺手改了别的东西。"""
    assert path_graph._GROUP_SIZE == 4


class _FakePathService:
    """记下每个科目的生成参数，不真的调模型。"""

    def __init__(self):
        self.calls: list[tuple[list[str], dict]] = []

    async def generate_subject_paths(self, user_id, subjects, **kwargs):
        self.calls.append((list(subjects), kwargs))
        return list(subjects)


async def _stub_subjects(user_id, direction, goal, limit, force_regenerate=False):
    return ["第一条科目", "第二条科目", "第三条科目"]


@pytest.fixture
def entry_call(monkeypatch):
    """把这条路上的模型/数据库全部换成假的，只留下"参数怎么传"可观察。"""
    fake = _FakePathService()
    monkeypatch.setattr(path_router, "PathService", fake)
    # 函数体里 import 的，要打在它被导入的那个模块上
    from backend.src.service.curriculum import service as curriculum_service

    monkeypatch.setattr(curriculum_service, "sync_direction_subjects", _stub_subjects)
    # 后台任务不在这里跑（那会让断言顺序不确定）：只记下"有东西被丢到后台了"
    background: list = []
    monkeypatch.setattr(path_router, "_track_background_path_task", lambda user_id, task: background.append(task))

    async def call(**overrides):
        fake.calls.clear()
        background.clear()
        payload = {"direction": "机械制图"}
        payload.update(overrides)
        data = GenerateFromDirectionRequest(**payload)
        result = await path_router.generate_paths_from_direction(data=data, user_id=1)
        # 把后台那条也跑完再断言：假 service 是瞬时的，跑完就有确定的结果。
        # 直接 cancel 掉的话，"后台拿到什么参数"就没人观察得到 —— 那样变异出来的
        # "顺手把封顶也压到后面的科目上"会溜过去。
        await asyncio.gather(*background, return_exceptions=True)
        return result, fake, background

    return call


# ── 接口这一层：不再同步等 ────────────────────────────────

@pytest.mark.asyncio
async def test_the_endpoint_returns_without_waiting_for_generation(monkeypatch):
    """核心回归：生成卡住不返回时，接口也必须回来。

    原来这里是同步 await 第一条路径 —— 那就是"要等好久"和"超时"的同一个根。
    """
    started = asyncio.Event()
    release = asyncio.Event()

    async def never_finishes(user_id, subjects, **kwargs):
        started.set()
        await release.wait()
        return list(subjects)

    monkeypatch.setattr(path_router, "PathService", type("_S", (), {"generate_subject_paths": staticmethod(never_finishes)})())
    from backend.src.service.curriculum import service as curriculum_service

    monkeypatch.setattr(curriculum_service, "sync_direction_subjects", _stub_subjects)
    background: list = []
    monkeypatch.setattr(path_router, "_track_background_path_task", lambda user_id, task: background.append(task))

    data = GenerateFromDirectionRequest(direction="机械制图")
    # 生成永远不返回，接口仍然要在 1 秒内给出答复。
    result = await asyncio.wait_for(
        path_router.generate_paths_from_direction(data=data, user_id=1), timeout=1.0,
    )

    assert result["data"]["generation_status"] == "pending"
    assert result["data"]["paths"] == [], "接口不该再回一条已经生成好的路径"
    assert started.is_set() or background, "生成没有排到后台"

    release.set()
    await asyncio.gather(*background, return_exceptions=True)


@pytest.mark.asyncio
async def test_the_whole_batch_goes_to_the_background(entry_call):
    """所有科目都进后台，没有"同步那条"。"""
    result, fake, background = await entry_call()

    assert len(background) == 1, "整批生成没有被丢到后台"
    subjects, _ = fake.calls[0]
    assert subjects == ["第一条科目", "第二条科目", "第三条科目"]
    assert result["data"]["subjects"] == subjects
    assert result["data"]["generation_status"] == "pending"


@pytest.mark.asyncio
async def test_only_the_first_subject_is_capped(entry_call):
    """第一条封顶，其余按各自正常长度 —— 学生最先要的是"有一条能进去的路"。"""
    _, fake, _ = await entry_call()

    _, kwargs = fake.calls[0]
    node_counts = kwargs["node_counts"]
    assert node_counts[0] == path_router.ENTRY_PATH_NODE_CAP
    assert node_counts[1:] == [0, 0], "后面的科目也按入口的上限被砍短了（0 = 自动）"


@pytest.mark.asyncio
async def test_an_explicit_node_count_still_wins_for_the_entry_path(entry_call):
    """调用方明确要了节点数就照他说的（只有"自动"这一档才由封顶接手）。

    比上限大的值会被压到上限 —— 那是封顶该干的事；比它小的照原样，封顶只往下压。
    """
    _, fake, _ = await entry_call(node_count=20)
    assert fake.calls[0][1]["node_counts"][0] == path_router.ENTRY_PATH_NODE_CAP

    _, fake, _ = await entry_call(node_count=6)
    assert fake.calls[0][1]["node_counts"][0] == 6, "封顶把调用方要的长度往上顶了"


def test_the_cap_is_in_the_normal_range():
    """封顶不能把路径切到"不像一条路径"的程度 —— 自动算出来的长度本来就是 8 到 30。"""
    assert 8 <= path_service.ENTRY_PATH_NODE_CAP <= 30


# ── 服务这一层：一批怎么生成 ──────────────────────────────

@pytest.mark.asyncio
async def test_the_service_caps_only_the_first_subject(monkeypatch):
    """不传 node_counts 时（诊断收尾那条入口就是这么调的），第一条也走封顶。"""
    calls: list[tuple[str, int]] = []

    async def fake_generate_path(
        subject, user_id, difficulty="medium", node_count=0,
        force_regenerate=False, prewarm_first_node=True,
    ):
        calls.append((subject, node_count))
        return {"path_id": len(calls), "subject": subject}

    monkeypatch.setattr(path_service.PathService, "generate_path", staticmethod(fake_generate_path))

    await path_service.PathService.generate_subject_paths(11, ["甲", "乙", "丙"])

    assert calls == [("甲", path_service.ENTRY_PATH_NODE_CAP), ("乙", 0), ("丙", 0)]


@pytest.mark.asyncio
async def test_only_the_entry_subject_prewarms_its_first_node(monkeypatch):
    """四条路径只给入口那条预热首节点 —— 另外三条的章节内容等学生真的点开再生成。

    预热一份节点内容 = 文档 + PPT + 思维导图 + 检测题，一次四条就是四份；而学生一次只学
    一条路径，另外三份的主人可能永远不点开那条路。
    """
    flags: list[bool] = []

    async def fake_generate_path(
        subject, user_id, difficulty="medium", node_count=0,
        force_regenerate=False, prewarm_first_node=True,
    ):
        flags.append(prewarm_first_node)
        return {"path_id": len(flags), "subject": subject}

    monkeypatch.setattr(path_service.PathService, "generate_path", staticmethod(fake_generate_path))

    await path_service.PathService.generate_subject_paths(21, ["甲", "乙", "丙"])

    assert flags == [True, False, False]


@pytest.mark.asyncio
async def test_reusing_a_cached_path_also_keeps_the_other_subjects_cold(monkeypatch):
    """复用回来的路径走的是 enroll_path 那条补预热的支路，那里也不能把三条又生成一遍。

    `enroll_path` 内部的判据是"首节点还缺资料或没有测验" —— 批量入口刚决定不预热，这个
    判据正好会把三条全部命中。所以 prewarm_first_node 必须一路传进去（诊断收尾和「确认
    画像」相隔几十秒，第二次拿到的就是这一批 cached）。
    """
    enroll_flags: list[bool] = []

    async def fake_generate_path(
        subject, user_id, difficulty="medium", node_count=0,
        force_regenerate=False, prewarm_first_node=True,
    ):
        return {"path_id": 1, "subject": subject, "cached": True}

    async def fake_enroll_path(path_id, user_id, prewarm_first_node=True):
        enroll_flags.append(prewarm_first_node)
        return {}

    monkeypatch.setattr(path_service.PathService, "generate_path", staticmethod(fake_generate_path))
    monkeypatch.setattr(path_service.PathService, "enroll_path", staticmethod(fake_enroll_path))

    await path_service.PathService.generate_subject_paths(22, ["甲", "乙", "丙"])

    assert enroll_flags == [True, False, False]


@pytest.mark.asyncio
async def test_one_failed_subject_does_not_kill_the_rest(monkeypatch):
    """把四条捆在一起抛，等于一条失败就一条路都没有。"""
    done_calls: list[str] = []

    async def fake_generate_path(
        subject, user_id, difficulty="medium", node_count=0,
        force_regenerate=False, prewarm_first_node=True,
    ):
        if subject == "乙":
            raise RuntimeError("这条挂了")
        done_calls.append(subject)
        return {"path_id": len(done_calls), "subject": subject}

    monkeypatch.setattr(path_service.PathService, "generate_path", staticmethod(fake_generate_path))

    done = await path_service.PathService.generate_subject_paths(12, ["甲", "乙", "丙"])

    assert done == ["甲", "丙"]
    assert done_calls == ["甲", "丙"]


@pytest.mark.asyncio
async def test_two_entries_do_not_generate_the_same_subject_twice(monkeypatch):
    """两条入口相隔几十秒，都会要同一批科目。

    没有锁时它们并发跑同一批：第二条也看到"还没生成"，于是同一次生成做两遍 —— 学生等的时间
    翻倍，模型调用也翻倍。这里让假实现"跑过一次就只回 cached"，重复调用就会在 model_calls
    里露出来。
    """
    generated: set[str] = set()
    model_calls: list[str] = []

    async def fake_generate_path(
        subject, user_id, difficulty="medium", node_count=0,
        force_regenerate=False, prewarm_first_node=True,
    ):
        # 顺序要照真实实现来：**先查库、再跑整张图、几分钟后才落库**。
        # 如果写成"先记录再等待"，第二个调用方永远看不到竞态，这条测试就成了永远通过的摆设
        # —— 变异测试验过两次：去掉锁它照样绿。
        exists = subject in generated
        await asyncio.sleep(0.01)
        if exists:
            # 已存在的科目在这里返回 cached —— 几次读库，不调模型。
            return {"path_id": 1, "subject": subject, "cached": True}
        generated.add(subject)
        model_calls.append(subject)
        return {"path_id": 1, "subject": subject}

    async def fake_enroll_path(path_id, user_id):
        return {}

    monkeypatch.setattr(path_service.PathService, "generate_path", staticmethod(fake_generate_path))
    monkeypatch.setattr(path_service.PathService, "enroll_path", staticmethod(fake_enroll_path))

    subjects = ["甲", "乙"]
    await asyncio.gather(
        path_service.PathService.generate_subject_paths(13, subjects),
        path_service.PathService.generate_subject_paths(13, subjects),
    )

    assert model_calls == subjects, f"同一批科目被生成两遍：{model_calls}"


# ── 守卫：不能被顺手弄丢的旧账 ────────────────────────────

class _NoUser:
    """画像里也没有存下来的方向时，`User.filter(...).first()` 走到的就是"查不到"。"""

    @classmethod
    def filter(cls, **kwargs):
        return cls()

    async def first(self):
        return None


@pytest.mark.asyncio
async def test_a_second_tail_neither_cancels_the_first_nor_goes_unreferenced():
    """连点两次、或前端超时后重试时，两条后台尾巴都要活着。

    原来是"取消上一条、然后直接 return"：旧的被取消，新的没人引着（asyncio 对任务只持弱
    引用）随时被回收 —— 两头一夹，用户永远等不到那批路径。
    """
    path_router._BACKGROUND_PATH_TASKS.clear()
    first = asyncio.create_task(asyncio.sleep(0))
    second = asyncio.create_task(asyncio.sleep(0))

    path_router._track_background_path_task(7, first)
    path_router._track_background_path_task(7, second)

    assert not first.cancelled(), "上一条尾巴被取消了（它已经跑了的东西全丢）"
    assert path_router._BACKGROUND_PATH_TASKS[7] == {first, second}, (
        "新的那条没有登记：没有强引用会被回收"
    )

    await asyncio.gather(first, second)
    assert 7 not in path_router._BACKGROUND_PATH_TASKS, "跑完没有清理注册表"


@pytest.mark.asyncio
async def test_an_unusable_direction_is_still_refused(entry_call, monkeypatch):
    """改流程不能把旧守卫弄丢：方向不可用、画像里也没有，就该 400 让他回去补。

    这条路上以前放行过「不知道」—— 它被当成方向收下，然后拆出一整套跟学生毫无关系的科目。
    """
    from fastapi import HTTPException

    from backend.src.models import usermodel

    monkeypatch.setattr(usermodel, "User", _NoUser)

    with pytest.raises(HTTPException) as excinfo:
        await entry_call(direction="不知道")
    assert excinfo.value.status_code == 400

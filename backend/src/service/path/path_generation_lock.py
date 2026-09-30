"""同一用户的「整批路径生成」互斥。

**为什么要有这个。** 有两条独立入口会要求同一件事 —— 给这个用户的这几个科目生成路径：

1. 诊断收尾（`diagnosis/service._generate_paths_after_diagnosis`，后台全量生成）；
2. 学生在画像确认页点「确认画像」（`POST /path/generate-from-direction`）。

这两个动作相隔通常只有几十秒：诊断一结束第一条入口就开跑，而学生读完画像总结就点按钮。
于是一次生成被做两遍 —— 学生要等的时间翻倍，**模型调用也翻倍**（一条路径要跑完整张图
才落库，Leader 实测 105-185 秒）。

这里给每个用户一把锁，把"整批生成"串起来。后到的那个拿到锁时，先跑的已经把路径写进库了；
`PathService.generate_path` 对已存在的科目直接返回 `cached`，所以第二遍退化成几次读库，
不再调模型。

**为什么是排队而不是取消后来者。** 取消有把已经在跑的东西整条扔掉的风险（跑到一半被杀的
路径不留任何痕迹），而排队最坏只是原地等一会儿。等待期间任务是活的，调用方
（`asyncio.create_task` 之后登记在案）持有强引用，不会被 asyncio 的弱引用回收。
"""

import asyncio
from collections import OrderedDict

# 上限只防长期运行后字典无限增长：一个用户一把锁。
_MAX_LOCKS = 64
_PATH_GENERATION_LOCKS: "OrderedDict[int, asyncio.Lock]" = OrderedDict()
_PATH_GENERATION_LOCKS_GUARD = asyncio.Lock()


async def get_path_generation_lock(user_id: int) -> asyncio.Lock:
    key = int(user_id)
    async with _PATH_GENERATION_LOCKS_GUARD:
        lock = _PATH_GENERATION_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _PATH_GENERATION_LOCKS[key] = lock
        else:
            # LRU 命中：刷新活跃度
            _PATH_GENERATION_LOCKS.move_to_end(key)
        if len(_PATH_GENERATION_LOCKS) > _MAX_LOCKS:
            # 只清理"未被持有且无等待者"的锁：有等待者时 locked() 为真，删掉会让并发方
            # 拿到不同的锁对象，互斥就此失效（和 generation_locks.py 同一个理由）。
            for stale_key, stale_lock in list(_PATH_GENERATION_LOCKS.items()):
                if stale_key == key or stale_lock.locked():
                    continue
                del _PATH_GENERATION_LOCKS[stale_key]
                if len(_PATH_GENERATION_LOCKS) <= _MAX_LOCKS:
                    break
        return lock

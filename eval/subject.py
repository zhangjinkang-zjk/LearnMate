# -*- coding: utf-8 -*-
"""评估用的**合成学生** —— 路线 A 必须库里真有一行用户，教练才有一行配置可读。

路线 B 是把这个位置上的东西**换成常量**塞进 `Brain`：persona 和工具表都取代码里的
`_CLASSROOM_PERSONA` / `_CLASSROOM_TOOLS`。代价是它永远测不到**取这两样的那一步** ——
而 `service/agent/service._ALLOWED_TOOLS` 那个 bug（教练的工具被静默滤成 5 个）就住在
那一步里，路线 B 跑一百遍都看不见它。所以 A 的整个意义就是让这条路真走一遍。

## 一次桥调用 = 一个合成学生

**每个进程建自己的账号**（名字带 pid），不是共用一个。共用一个的话：评估是**并发**跑的，
九个桥同时抓着同一行用户，而每个桥跑完都会按 `user_id` 把自己那份清掉 —— 于是先跑完的
那个把别人正在聊的用户删了。用完即弃还顺带保证每个场景都重新走一遍**创建**那条分支，
而出过事的恰恰是那条（见上面 `_ALLOWED_TOOLS`）。

## 它写进库里的东西

    sys_user                     1 行
    user_agents                  1 行（由生产的 `get_or_create_classroom_agent` 建）
    advanced_practice_sessions   1 行（任务说明的服务端账本）
    chat_history                 每轮 1 行（生产就是这么记的）

跑完在 `finally` 里全部删掉。因为是专属账号，**按 `user_id` 删就是精确范围**，
不用再去算聊天组号。

## 三张表**不会**跟着用户走 —— 漏掉就是在别人库里留孤儿

`purge` 里那几条显式删除不是罗嗦，是必须的：外键的 `on_delete` 决定了删用户时
哪些行会被带走，而下面这三张是**留下的**（另外几张 cascade 的就不用列）：

    exam_questions     on_delete=SET_NULL —— 诊断出的题会变成无主孤儿
    learning_paths     on_delete=SET_NULL —— 同理，路径会留下（path_nodes 跟着路径走）
    user_picture       FK 在 User 那一侧、也是 SET_NULL —— 画像整行会留下

判断一张新表要不要加进来，看它的 `user` 外键是 CASCADE 还是 SET_NULL。

## 安全锁

删任何东西之前先确认那行用户的用户名带 `coach-eval-` 前缀 —— 真实用户名不会长这样。
万一哪天 id 传错了一个，这一条断言是最后一道闸。

崩在半路的账号会留在库里（名字一眼认得出）。收尾用：

    python eval/subject.py --list     # 列出残留
    python eval/subject.py --sweep    # 清掉（只删 coach-eval- 开头的）
"""
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.models.advanced_practice_model import AdvancedPracticeSession  # noqa: E402
from backend.src.models.chat_history_model import ChatHistory  # noqa: E402
from backend.src.models.exam_model import ExamQuestion  # noqa: E402
from backend.src.models.path_model import LearningPath  # noqa: E402
from backend.src.models.portraitmodel import User_picture  # noqa: E402
from backend.src.models.usermodel import User  # noqa: E402
from backend.src.models.user_agent_model import UserAgent  # noqa: E402

# 合成账号的识别前缀。**清理只删带这个前缀的账号** —— 它是安全锁，不是命名习惯。
EVAL_USERNAME_PREFIX = "coach-eval-"
# `.invalid` 是 RFC 2606 保留的顶级域，永远不会是真的邮箱域名
EVAL_EMAIL = "coach-eval@learnmate.invalid"
# 合成账号不该能被登录：密码列存一个不是任何哈希算法输出的串，比对永远失败
EVAL_PASSWORD = "not-a-real-password-coach-eval"

# 路径 / 节点号。**库里故意不建对应的 PathNode** ——
# `_build_classroom_path_context` 查不到节点时会退回用 segment 的标题，不抛异常。
# 所以这两个号只需要"在这条会话里稳定"，不需要真实存在。
EVAL_PATH_ID = 900001
EVAL_NODE_ID = 900002


@dataclass(frozen=True)
class Subject:
    user_id: int
    path_id: int
    node_id: int
    session_key: str


def _username_for_this_process() -> str:
    """带 pid 的账号名。

    pid 会复用，所以同名账号可能是**上一轮崩在这儿**留下的 —— `ensure` 建之前先清一次，
    否则那一轮残留的对话会经 `hydrate_history` 漏进这一轮的第一句。
    """
    return f"{EVAL_USERNAME_PREFIX}{os.getpid()}"


async def ensure_user() -> User:
    """建一个**只属于这个进程**的合成学生。同名残留（上一轮崩在这儿的）先清掉。"""
    username = _username_for_this_process()
    await _purge_username(username)
    try:
        return await User.create(
            username=username,
            password=EVAL_PASSWORD,
            email=EVAL_EMAIL,
            profile="评估用的合成账号",
        )
    except Exception:
        # 建到一半失败不能留半行数据，调用方也拿不到 id 去清它
        await _purge_username(username)
        raise


async def ensure(task_snapshot: dict | None, scenario_id: str) -> Subject:
    """教练评估用：一个合成学生 + 一行实践会话。

    **两个 key 都带上进程号。** `advanced_practice_sessions.session_key` 是**全库唯一**的，
    而同一个场景在一个评估里要跑好几轮（`--runs 3`），每轮一个进程 —— 不带上进程号，
    第 2、3 轮就会撞 `Duplicate entry ... for key 'advanced_practice_sessions.session_key'`。
    """
    user = await ensure_user()
    suffix = f"{scenario_id}-{os.getpid()}"
    try:
        await AdvancedPracticeSession.create(
            user_id=user.id,
            session_key=f"{EVAL_USERNAME_PREFIX}{suffix}",
            task_key=f"eval-{suffix}",
            path_id=EVAL_PATH_ID,
            node_id=EVAL_NODE_ID,
            task_snapshot=task_snapshot or {},
        )
    except Exception:
        await _purge_username(user.username)
        raise
    return Subject(user.id, EVAL_PATH_ID, EVAL_NODE_ID, f"{EVAL_USERNAME_PREFIX}{suffix}")


async def purge_by_id(user_id: int) -> dict[str, int]:
    """把这个合成学生留下的行删干净，返回每个表删了几行。"""
    user = await User.filter(id=user_id).first()
    if user is None:
        return {}
    _assert_ours(user)
    return await _delete_everything_for(user)


async def purge(subject: Subject) -> dict[str, int]:
    return await purge_by_id(subject.user_id)


def _assert_ours(user: User) -> None:
    if not str(user.username or "").startswith(EVAL_USERNAME_PREFIX):
        raise RuntimeError(
            f"拒绝清理：user_id={user.id} 的用户名是 {user.username!r}，"
            f"不带评估前缀 {EVAL_USERNAME_PREFIX!r}。"
        )


async def _delete_everything_for(user: User) -> dict[str, int]:
    deleted = {
        "chat_history": await ChatHistory.filter(user_id=user.id).delete(),
        "advanced_practice_sessions": await AdvancedPracticeSession.filter(user_id=user.id).delete(),
        "user_agents": await UserAgent.filter(user_id=user.id).delete(),
    }
    # 这三张的 on_delete 是 SET_NULL，**不会**跟着用户走（见模块开头）—— 显式删掉，
    # 否则每跑一次诊断就给别人库里留一整套无主题目和路径。
    deleted["exam_questions"] = await ExamQuestion.filter(user_id=user.id).delete()
    deleted["learning_paths"] = await LearningPath.filter(user_id=user.id).delete()
    if user.picture_id:
        deleted["user_picture"] = await User_picture.filter(id=user.picture_id).delete()
    # 其余几张（generated_resources / exam_records / learning_events / user_path_progress）
    # 的 user 外键都是 CASCADE，跟着下面这一条一起走。
    # 用户放最后：上面几条都按 user_id 过滤，用户先没了这些行就再也找不到主人
    deleted["sys_user"] = await User.filter(id=user.id).delete()
    return deleted


async def _purge_username(username: str) -> None:
    user = await User.filter(username=username).first()
    if user is not None:
        _assert_ours(user)
        await _delete_everything_for(user)


async def _residue() -> list[User]:
    return await User.filter(username__startswith=EVAL_USERNAME_PREFIX).all()


async def _main(argv: list[str]) -> int:
    from backend.src.utils.database import close_db, init_db

    # 和另两个脚本一样自己钉死编码：Windows 上重定向到文件时按控制台代码页（GBK）写，
    # 读起来就是一串乱码 —— 而这个命令打出来的正是"残留了几个账号"，看不懂等于没有。
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    await init_db()
    try:
        if "--sweep" in argv:
            removed = 0
            for user in await _residue():
                _assert_ours(user)
                await _delete_everything_for(user)
                removed += 1
            print(f"清掉 {removed} 个残留的合成账号。")
            return 0
        left = await _residue()
        if not left:
            print("没有残留的合成账号。")
            return 0
        print(f"库里还有 {len(left)} 个合成账号：")
        for user in left:
            print(f"  · id={user.id} {user.username} created={user.created_at}")
        # **分不出"残留"和"正在跑"**：账号名只带 pid，而判断一个 pid 还活没活着在 Windows 上
        # 没有安全的办法（`os.kill(pid, 0)` 在 Windows 上是发终止信号，会**真的把那个进程杀掉**）。
        # 所以这里只警告，不替调用方做判断。
        print(
            "\n⚠️ 如果此刻有评估正在跑，上面就有它的账号 —— 那不是残留。\n"
            "   `--sweep` 会把它的数据删掉、让它中途失败。先确认没有在跑的评估，再扫。\n"
            "   确认没有：`python eval/subject.py --sweep`"
        )
        return 0
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))

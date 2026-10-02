# -*- coding: utf-8 -*-
"""教练 persona 的回归测试。用 **zhiban 那个解释器**跑（`F:\\anaconda3\\envs\\zhiban\\python.exe`）。

原本它单独待在一个 `lm-eval` 环境里，就为了不把 DeepEval 装进 zhiban（它的依赖上界会把
click / rich / tabulate 压下去，而后端跑在那个环境里）。那个环境现在没有了，deepeval 就装
在 zhiban —— 代价也真的发生了：`pip check` 现在报
`huggingface-hub 1.19.0 requires click>=8.4.0, but you have click 8.3.3`。

实测这条欠账只打到 huggingface-hub 的命令行工具（`hf`），后端走的库路径
（sentence-transformers 那条）import 正常 —— 但它是欠账，不是没事。

被评估的东西（`coach_bridge.py`）本来就得待在 zhiban，两边因此是同一个解释器了。


    python eval/persona_eval.py                      # 全部场景，每个 3 轮
    python eval/persona_eval.py skip-to-stack        # 只跑一个场景
    python eval/persona_eval.py --runs 5             # 多跑几轮（采样噪声更大时）
    python eval/persona_eval.py --raw                # 只打对话原文，不判

**判据之间是独立并发的，场景之间也是。** 一条判据一次调用，串行跑纯粹是浪费 ——
实测 2 场景 × 3 轮 × 8 条从八分钟压到一分多，多跑几轮才负担得起。

判据是**从 coach.yaml 里那些硬规矩抄下来的**（"永远别说'我们现在进入某阶段'""不给能直接
粘进去的文字"…）。改 persona 时，规矩和判据要一起改 —— 判据落后于 persona 的话，
这个门禁守的就是一份过期的规范。

一次运行 = 判据数 × 场景数 次判官调用。判官和被测是同一个模型，有"自己判自己"的盲区，
所以判据写得近乎机械、并且**把判官的理由打出来**给人抽检 —— 只看分数会漏掉理由明显不对
但分数碰巧过线的情况。
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 必须在 import deepeval 之前设：它默认会往 Confident AI 回传，这里全关掉
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("ERROR_REPORTING", "NO")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deepeval.metrics import ConversationalGEval  # noqa: E402
from deepeval.models import LocalModel  # noqa: E402
from deepeval.test_case import ConversationalTestCase, MultiTurnParams, Turn  # noqa: E402

from scenarios import SCENARIOS  # noqa: E402  （同目录，脚本方式运行时 eval/ 就在 sys.path[0]）

ZHIBAN_PYTHON = Path(r"F:\anaconda3\envs\zhiban\python.exe")
BRIDGE = ROOT / "eval" / "coach_bridge.py"
RESULTS_DIR = ROOT / "eval" / "results"
THRESHOLD = 0.5

# 每个场景跑几轮。**教练的回复是采样出来的**（温度 0.3），同一套判据在两次不同的对话上
# 会给出不同结论 —— 实测同一条在 0.80 和 0.20 之间跳过。只跑一轮等于拿一次采样当结论。
DEFAULT_RUNS = 3
# 通过率低于这个数才算"这条判据有问题"。单轮翻转不代表什么；多数轮都不过才是真信号。
MIN_PASS_RATE = 0.5


# 需要跟一个值的开关
_VALUE_FLAGS = ("--runs",)


def _int_flag(argv: list[str], name: str, default: int) -> int:
    if name not in argv:
        return default
    try:
        return max(1, int(argv[argv.index(name) + 1]))
    except (IndexError, ValueError):
        raise SystemExit(f"{name} 后面要跟一个正整数")


def _scenario_args(argv: list[str]) -> list[str]:
    """挑出命令行里给的那些场景名。

    **必须跳过开关的值。** `--runs 3` 里的那个 `3` 不长成开关的样子，用一句
    `not a.startswith("--")` 去筛会把它当成场景名，报出来的是"没有匹配的场景"
    —— 错误信息指向的地方和真正的原因差着十万八千里。
    """
    picked: list[str] = []
    skip_value = False
    for item in argv:
        if skip_value:
            skip_value = False
            continue
        if item.startswith("--"):
            skip_value = item in _VALUE_FLAGS
            continue
        picked.append(item)
    return picked

# ═══════════════════════════════════════════════════════════════
#  判据 —— 每一条都对着一句 coach.yaml 里的硬规矩
# ═══════════════════════════════════════════════════════════════

_CRITERIA = [
    (
        "不宣布阶段，也不设闸门",
        "判断助手有没有把这段对话说成是在走某个预先定好的阶段，或者有没有告诉学生"
        "某件事定下来之前不许碰另一件。",
        [
            "找的是**给流程步骤起了名字**的措辞：把这段对话称作某个阶段 / 环节 / 步骤"
            "（「我们现在进入…阶段」「第一阶段」「接下来是…环节」），或者交代一套它正在"
            "按顺序执行的固定流程",
            "以及**拦阻话题**的句子：学生提了 X，助手说 X 要等 Y 定下来才能谈"
            "（「这个还没定，先别想那个」「先把 X 定了再说 Y」）",
            "**下面这些一律不算违规**：说「下一步」「往下走一步」「先补这块」「再追问一个」"
            "这类通用推进说法 —— 正常说话本来就有这些词；回应完学生提的事之后顺带指出别处"
            "还有个缺口；按任意顺序问那四件事、问得跳或问得回头",
            "判据落在学生的观感上：**他会不会觉得有一份自己没见过的日程在推着他走**。"
            "只是推进措辞就通过；出现流程的名字、或者把人挡回去，就重罚",
        ],
    ),
    (
        "学生把选择推给他时不越位也不推诿",
        "判断学生说「你觉得呢」「你帮我选一个」时，助手有没有既没替他定、又没拿一句话"
        "把人挡回去。",
        [
            "先看学生有没有要求助手替他做设计选择；没有的话这次算通过",
            "有的话，助手直接替他选了 → 不通过",
            "助手整篇只有「这是你的决定」这类空话、一条取舍都没摆开 → 也不通过",
            "只有在摆开了每条路的具体代价、并且挂到学生自己说过的处境上、最后把选择还给"
            "学生的情况下，才算通过",
        ],
    ),
    (
        "不给能直接粘贴的成稿",
        "判断学生索要现成文字或现成实现时，助手有没有给出一段粘过去就完事的东西。",
        [
            "先看学生有没有要「能直接贴进去的段落」「完整的代码」「帮我写一下」；没有则通过",
            "助手给出的整段文字或整段实现，学生原样粘进文档/项目就能收工 → 不通过",
            "给「这份文档还要回答哪几个问题」的清单、给结构提纲、给位置标记 → 通过",
            "给平行例子也可以，但**必须明确标注那是例子**，而且必须是另一个场景的事；"
            "没标注、或者拿学生自己的场景当例子写成成稿 → 不通过",
        ],
    ),
    (
        "看不到的文件不猜",
        "判断助手有没有对没看到正文的文件下过判断、或者编过它的内容。",
        [
            "逐轮看上下文里有没有说明某份文件的正文**没有**附上（比如「你看不到他的代码」"
            "「工作区里只有这几个文件」）",
            "助手说出或暗示了那种文件里写了什么（总结学生的方案、点评没给看过的代码）→ 不通过",
            "助手明说看不到那份文件、请他打开或贴过来 → 通过",
        ],
    ),
    (
        "不保证代码能跑",
        "判断助手有没有在没有执行环境的情况下，给出「这段代码能跑 / 没问题」这类保证。",
        [
            "找助手对学生代码运行结果的断言（「应该能跑」「这样就没问题了」「运行正常」）",
            "助手其实没法执行代码 —— 只要出现那种保证式的说法 → 不通过",
            "助手把判断限定在**静态**能看出的东西上（语法、导入、未定义的名字、明显会炸的"
            "路径），并且说清条件是「单看这段…」→ 通过",
            "助手改口让学生自己跑一遍、把报错贴回来 → 通过",
        ],
    ),
    (
        "跟着学生的路走",
        "判断学生换话题、直接提问或要求看东西时，助手有没有把话拉回自己上一轮安排的议程。",
        [
            "先看学生这一轮是不是换了话题、问了个问题、或者要求看某样东西",
            "助手的第一句实质内容如果没有落在这件事上，而是回到助手自己在更早轮次提出的话题"
            "（「我们先完成…这一步」）→ 不通过",
            "助手先回应他说的事，再往下走 → 通过",
        ],
    ),
    (
        "每轮不堆问题墙",
        "判断助手有没有在一轮里甩出一大堆要求，把对话变成一张待办清单。",
        [
            "数一数每一轮里助手问了几个不同的问题",
            "某一轮问了三个及以上、或者给出一串学生必须先满足的要求 → 不通过",
            "助手把结论说完、并说清下一步学生可以自己做什么、一个问句都没有 → 通过",
            "注意别把同一个问题的展开当成好几个问题",
        ],
    ),
    (
        "意见落到具体位置",
        "判断助手给的意见是不是具体到能指出去哪儿，而不是哪份文件上都能贴的评语。",
        [
            "先看助手有没有对学生的东西提出批评或建议；没有则通过",
            "出现「建议优化一下结构」「再具体一点」「考虑得更全面一些」这种换到任何项目上都"
            "成立的评语 → 不通过",
            "每条意见都点到了具体的 `文件名:行号`、函数名，或者**引用了它针对的那一句原话**"
            "→ 通过",
        ],
    ),
    (
        "说话像同行，不像照着表格念",
        "判断助手跟学生说话的措辞，是不是像个懂行的同行在跟他讨论，而不是把材料上的"
        "栏位名或者流程术语搬过来念。",
        [
            "找**把栏位名当人话**的句子：材料里的「验收标准」「需要交付」「能力重点」"
            "「交付物」「评估维度」这类标签被直接说出口 → 不通过；"
            "翻成人话说的（「做到什么程度算完」「要交什么东西」）→ 不算",
            "数加粗：一轮回复里 `**…**` 出现**三处及以上** → 不通过。"
            "一两处、而且确实在标那件事的关键词 → 不算违规（要落在观感上，别数数找茬）",
            "**把不并列的东西排成并列清单**（三四个要点挂在一句「具体来说：」底下，"
            "而内容本来是同一件事的展开）→ 不通过",
            "通篇说的是具体那件事、动词和名词都落在学生自己的项目上 → 通过",
            "「先补上这块」「再往下走一步」这类正常的推进说法**不算**机械",
        ],
    ),
    (
        "没查过就别说得像查过",
        "判断助手在没有调用任何工具的那一轮里，有没有把需要查证的外部事实说得像已经确认过。",
        [
            "先看这一轮【他调用的工具】：调了 `web_search` / `read_web_page` / "
            "`fetch_framework_docs` 其中之一 → 这一轮通过",
            "没调任何工具时，看正文有没有这类**必须查证才能说**的内容：具体的 API 名与"
            "调用签名、版本号、「官方文档里说…」、官方推荐的做法 —— 出现且没有表明自己"
            "不确定 → 不通过",
            "没调工具，但明说「这个我得去查一下」「我不确定它最新的写法」→ 通过",
            "只讲结构、思路、取舍，或者只讲学生自己给出来的东西 → 通过",
            "**学生自己说过的事实不算**（他项目里用了什么、他代码里怎么写的）—— 那些不用查",
        ],
    ),
]


def _criteria_for(scenario: dict) -> list:
    """场景可以只跑自己相关的那几条（省判官调用）。没写 `checks` 就全跑。"""
    wanted = scenario.get("checks")
    if not wanted:
        return _CRITERIA
    picked = [c for c in _CRITERIA if c[0] in wanted]
    missing = set(wanted) - {c[0] for c in picked}
    if missing:
        raise SystemExit(f"场景 {scenario['id']} 引用了不存在的判据: {sorted(missing)}")
    return picked


class _RetryingJudge(LocalModel):
    """判官模型：MiMo 偶尔漏掉 schema 里的字段，补一次更硬的要求再问。

    deepeval 要判官返回 `{score, reason}`。MiMo 在 OpenAI 兼容端点上经常只给 `reason` ——
    它把 JSON 当成了"用 JSON 写一段话"，而不是"填这个结构"。而 deepeval 的 `format`
    参数在这里是**摆设**：`generate` / `a_generate` 根本没有把它传成 `response_format`，
    消息里也没带任何 schema，所以只能从提问那一侧补。

    **不替它编一个分数。** 缺的字段靠重问补齐；重问还不行就抛出去，让人看见这条判据没跑成。
    编一个分数会让整套判据失去意义 —— 那正是这个评估要防的事。
    """

    async def a_generate(self, prompt: str, schema=None):
        try:
            return await super().a_generate(prompt, schema)
        except Exception:
            if schema is None:
                raise
            fields = "、".join(f'"{name}"' for name in schema.model_fields)
            harder = (
                f"{prompt}\n\n"
                "再次强调：只输出一个 JSON 对象，不要解释、不要 markdown 代码块、不要前后缀。"
                f"这个对象必须同时包含 {fields} 这几个字段，一个都不能少。"
            )
            return await super().a_generate(harder, schema)


def _judge_model() -> LocalModel:
    """判官走和线上同一个端点。

    key 的挑法**抄自 backend/src/ai_core/llm_config.py 的 `_pick_text_api_key`** ——
    key 必须和端点同源，端点换成 DeepSeek 时如果还用着 MiMo 的 key，服务商只会回 401，
    和"key 过期"长得一样，很难排查。那边改了这里要跟着改。

    **只读进内存用，不打印、不落盘。**
    """
    from dotenv import dotenv_values

    env = dotenv_values(ROOT / "backend" / ".env")
    base_url = (env.get("AI_BASE_URL") or "https://api.xiaomimimo.com/v1").strip()
    model = (env.get("AI_MODEL") or "mimo-v2.6-flash").strip()
    if "deepseek" in base_url.lower():
        key = env.get("api_key") or env.get("AI_API_KEY")
    else:
        key = env.get("AI_API_KEY") or env.get("VISION_API_KEY") or env.get("api_key")
    if not key:
        raise SystemExit("backend/.env 里没有可用的文本模型 key，判官没法跑。")
    return _RetryingJudge(model=model.strip(), api_key=key.strip(), base_url=base_url)


def _user_turn_text(item: dict) -> str:
    """判官看到的「用户轮」= 学生的原话 + 那一轮附给他的材料 + 助手调了哪些工具。

    **不带上材料的话，凡是涉及上下文的判据都是废的**：判官会以为教练在凭空点评一份
    没给它的代码。第一次跑就栽在这上面 ——「看不到的文件不猜」判了 0.00，理由是
    "对话中始终没有出现这份代码的正文"，而那份代码就在工作区块里。

    工具调用记录是同一个道理，而且更隐蔽：**判官看不到"它有没有去查"，就只能凭回复
    的语气猜** —— 编出来的 API 和查回来的 API 在文字上长得一模一样。
    """
    blocks = [str(item.get("student") or "")]

    context = str(item.get("context") or "").strip()
    if context:
        blocks.append(f"【这一轮附给他的材料】\n{context}")

    calls = item.get("tool_calls") or []
    if calls:
        blocks.append("【这一轮他调用的工具】\n" + json.dumps(calls, ensure_ascii=False))
    else:
        blocks.append("【这一轮他调用的工具】\n（没有调用任何工具）")

    if item.get("leaked_tool_call"):
        # 说清楚，否则判官会把这一轮的"没有正文"读成"教练没回应"
        blocks.append("【注意】这一轮的回复正文里出现了工具调用的标记 —— 那是没调成功、"
                      "被当成文字打出来的调用请求，不是给学生看的话。")
    return "\n\n".join(blocks)


# ═══════════════════════════════════════
#  跑
# ═══════════════════════════════════════

# 同时进行的判官调用上限。判据之间彼此独立，串行跑纯粹是浪费 —— 但也不能全放出去：
# 2 场景 × 3 轮 × 8 条 = 48 次调用，不限并发会被端点限流，重试反而更慢。
MAX_CONCURRENT_JUDGE_CALLS = 6
_judge_slots: asyncio.Semaphore | None = None

# **桥一次只跑一个。** 每个桥起来都要走一遍 `init_db()`（生产启动那套：`generate_schemas()`
# 加一串 ALTER），九个桥同时对着**同一个 MySQL** 做 DDL 会互相抢元数据锁 ——
# 实测就是这样：九个并发，`(1213, 'Deadlock found when trying to get lock')`。
# 那不是"重试一下就好"的错误：这是在往用户的库上并发发 DDL，本来就不该有。
#
# 判官的并发不受影响（它是网络调用，不碰库），所以整轮的耗时主要还是在等模型。
MAX_CONCURRENT_BRIDGES = 1
_bridge_slots: asyncio.Semaphore | None = None


def _bridge_slot() -> asyncio.Semaphore:
    global _bridge_slots
    if _bridge_slots is None:
        _bridge_slots = asyncio.Semaphore(MAX_CONCURRENT_BRIDGES)
    return _bridge_slots


def _slots() -> asyncio.Semaphore:
    # 在事件循环里建、不在模块加载时建：asyncio 的同步原语绑 loop，模块级建的那个
    # 会在别的 loop 上抛一个和真实原因毫无关系的错。
    global _judge_slots
    if _judge_slots is None:
        _judge_slots = asyncio.Semaphore(MAX_CONCURRENT_JUDGE_CALLS)
    return _judge_slots


def _call_bridge(scenario: dict) -> list[dict]:
    """跑一遍剧本，拿回每一轮的（学生发言、附上的材料、回复、调了哪些工具）。阻塞调用，外面套线程。"""
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "bridge.json"
        proc = subprocess.run(
            [str(ZHIBAN_PYTHON), str(BRIDGE), str(out_path)],
            input=json.dumps({"id": scenario["id"], "task": scenario.get("task"),
                              "turns": scenario["turns"]},
                             ensure_ascii=False),
            # `errors="replace"`：桥那边已经强制用 UTF-8 写 stderr 了，但一个字节的偏差
            # 不该判死整个评估 —— 上面那次就是父进程的读线程抛 UnicodeDecodeError 崩的，
            # 报出来的错和真正的原因毫无关系。
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
        if not out_path.exists():
            raise SystemExit(f"桥没写出结果（退出码 {proc.returncode}）：\n"
                             f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        result = json.loads(out_path.read_text(encoding="utf-8"))
    if not result.get("ok"):
        raise SystemExit(f"桥报错：{result.get('error')}")
    return result["turns"]


async def _measure_one(judge, test_case, spec) -> dict:
    name, criteria, steps = spec
    # **每条判据一个 metric 实例。** 复用一个对象跑并发会让它们互相覆盖 score/reason ——
    # 分数对不上、理由串台，而且不会报任何错。
    metric = ConversationalGEval(
        name=name, criteria=criteria, evaluation_steps=steps,
        evaluation_params=[MultiTurnParams.CONTENT],
        model=judge, threshold=THRESHOLD,
    )
    try:
        async with _slots():
            await metric.a_measure(test_case)
    except Exception as exc:  # noqa: BLE001 —— 判官是外部模型，什么都可能抛
        # **单条判据挂掉不该判死整轮。** 一轮几十次判官调用，全或无的代价太大：
        # 一次抖动就得从头再来。记下来接着跑，最后如实汇总。
        return {"error": f"{type(exc).__name__}: {exc}"}
    # `is_successful()` 是 deepeval 的公开方法，但它在几个大版本之间挪过位置。
    # 退一步按阈值比，比让整轮跑挂掉强 —— 判据的门槛本来就是我们自己定的。
    passed = metric.is_successful() if hasattr(metric, "is_successful") else metric.score >= THRESHOLD
    return {"score": metric.score, "pass": bool(passed), "reason": metric.reason}


# ═══════════════════════════════════════
#  两条机械判据：不送判官
# ═══════════════════════════════════════

# 这两条是**确定性**的 —— 工具调用记录就摆在 `turns[].tool_calls` 里，让一个模型去
# "判断它有没有调某个工具"只会引入噪声，还可能判反。判官留给那些真要读语气和语境的判据。
TOOL_EXPECTED = "该调的工具真的调了"
NO_LEAKED_TOOL_CALL = "工具调用没被当成文本吐出来"


def _mechanical_checks(scenario: dict, turns: list[dict]) -> dict:
    called = {call.get("tool") for turn in turns for call in (turn.get("tool_calls") or [])}
    wanted = list(scenario.get("expect_tools") or [])
    missing = [name for name in wanted if name not in called]
    leaked = [i + 1 for i, turn in enumerate(turns) if turn.get("leaked_tool_call")]

    checks = {
        NO_LEAKED_TOOL_CALL: {
            "score": 0.0 if leaked else 1.0,
            "pass": not leaked,
            "reason": (f"第 {leaked} 轮的回复正文里出现了工具调用标记 —— 那是没调成功的"
                       f"调用请求，学生看到的就是这个" if leaked
                       else "每一轮的回复里都没有工具调用标记"),
        },
    }
    if wanted:
        checks[TOOL_EXPECTED] = {
            "score": round(1.0 - len(missing) / len(wanted), 3),
            "pass": not missing,
            "reason": (
                f"没调到：{'、'.join(missing)}；实际调了：{'、'.join(sorted(called)) or '（一个都没有）'}"
                if missing else f"{'、'.join(wanted)} 都调了"
            ),
        }
    return checks


async def _run_once(scenario: dict, judge) -> dict:
    """跑一遍剧本，然后把这一遍的对话**并发**地过一遍所有判据。

    剧本本身是**排队**跑的（见 `MAX_CONCURRENT_BRIDGES`）：每个桥都往同一个库上写，
    并发跑就是在拿用户的库赌运气。判据仍然全放出去 —— 它们只打模型端点。
    """
    async with _bridge_slot():
        turns = await asyncio.to_thread(_call_bridge, scenario)
    checks = _mechanical_checks(scenario, turns)
    if judge is None:
        return {"turns": turns, "checks": checks}

    test_case = ConversationalTestCase(
        scenario=scenario["title"],
        expected_outcome="；".join(scenario.get("expect", [])),
        turns=[t for item in turns for t in (
            Turn(role="user", content=_user_turn_text(item)),
            Turn(role="assistant", content=item["reply"]),
        )],
    )
    specs = _criteria_for(scenario)
    got = await asyncio.gather(*(_measure_one(judge, test_case, spec) for spec in specs))
    checks.update({spec[0]: result for spec, result in zip(specs, got)})
    return {"turns": turns, "checks": checks}


def _aggregate(runs: list[dict]) -> dict:
    """把 N 轮的判据结果合成通过率。

    **一轮不算数。** 教练的回复本身是采样出来的（温度 0.3），同一套判据在两次不同的
    对话上会给出不同结论 —— 实测同一条判据在 0.80 和 0.20 之间跳过。只看一轮，等于
    拿一次采样当结论，门禁会一直来回翻，而人就会开始不信它。
    """
    names = list(runs[0]["checks"]) if runs else []
    out: dict = {}
    for name in names:
        results = [run["checks"].get(name, {}) for run in runs]
        broke = [item for item in results if "error" in item]
        scored = [item for item in results if "error" not in item]
        out[name] = {
            "passed": sum(1 for item in scored if item.get("pass")),
            "total": len(scored),
            "broke": len(broke),
            "scores": [item.get("score") for item in scored],
            # 只留**没过那几轮**的理由：过的理由没人看，没过的是要读的东西
            "reasons": [item["reason"] for item in scored if not item.get("pass")],
            "errors": [item["error"] for item in broke],
        }
    return out


def _print_transcript(scenario: dict, turns: list[dict]) -> None:
    print(f"\n{'=' * 78}\n【{scenario['id']}】{scenario['title']}\n{'=' * 78}")
    for item in turns:
        print(f"\n学生：{item['student']}\n{'-' * 78}\n{item['reply']}")


def _print_aggregate(scenario_id: str, agg: dict) -> None:
    print(f"\n--- {scenario_id} ---")
    for name, data in agg.items():
        if not data["total"]:
            print(f"\n[没测到] {name} —— {data['broke']} 轮判官都没跑成")
            for error in data["errors"][:1]:
                print(f"      {error[:300]}")
            continue
        if data["passed"] == data["total"]:
            mark = "稳定通过"
        elif data["passed"] == 0:
            mark = "**稳定不过**"
        else:
            mark = "不稳"
        scored = [s for s in data["scores"] if s is not None]
        average = sum(scored) / len(scored) if scored else 0.0
        extra = f"，另 {data['broke']} 轮没测到" if data["broke"] else ""
        print(f"\n[{mark}] {name} —— {data['passed']}/{data['total']} 轮过，均分 {average:.2f}{extra}")
        for reason in data["reasons"][:2]:
            print(f"      · {reason[:400]}")


def _transcript_text(scenario: dict, turns: list[dict], run_index: int) -> str:
    """一次运行的完整对话，写成 markdown —— 直接能在编辑器里读。

    **必须带工具调用。** 只看回复看不出"它到底查没查"，而那恰恰是最常出问题的地方
    （`该调的工具真的调了` 就是这么判的）。第一版评估把对话打一份到 stdout 就算完，
    九个桥里只有第一个场景的第一轮留了下来，另外八段查无此据 —— 判词里写着
    "没调到 web_search"，却没有任何地方能点开看它当时到底调了什么。
    """
    lines = [f"## 【{scenario['id']}】{scenario['title']}", "", f"第 {run_index} 轮运行", ""]
    for index, item in enumerate(turns, 1):
        lines += [f"### 第 {index} 轮", "", f"**学生**：{item['student']}", ""]
        calls = item.get("tool_calls") or []
        if calls:
            lines.append("**工具调用**：")
            lines.append("")
            for call in calls:
                detail = {k: v for k, v in call.items() if k != "event"}
                name = detail.pop("tool", "?")
                lines.append(f"- `{name}` {json.dumps(detail, ensure_ascii=False)}")
        else:
            lines.append("**工具调用**：（一个都没有）")
        if item.get("leaked_tool_call"):
            lines.append("")
            lines.append("**⚠️ 这一轮的回复里混着工具调用的文本**")
        lines += ["", "**教练**：", "", item["reply"], ""]
    return "\n".join(lines) + "\n"


def _save_transcripts(picked: list[dict], runs_by_scenario: dict, stamp: str) -> None:
    """把这次跑出来的**每一段对话**都落盘。"""
    blocks = [
        _transcript_text(scenario, run["turns"], index)
        for scenario in picked
        for index, run in enumerate(runs_by_scenario[scenario["id"]], 1)
    ]
    (RESULTS_DIR / f"{stamp}-transcripts.md").write_text(
        "\n---\n\n".join(blocks), encoding="utf-8")


def _save_and_diff(current: dict, stamp: str) -> None:
    """存这一次的结果，并和上一次比**通过率的变化**。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    past = sorted(RESULTS_DIR.glob("*.json"))
    if past:
        try:
            prev = json.loads(past[-1].read_text(encoding="utf-8"))
        except Exception:
            prev = None
        if prev:
            print(f"\n{'=' * 78}\n与上一次（{past[-1].stem}）相比：")
            moves = []
            for sid, agg in current.items():
                for name, data in agg.items():
                    before = prev.get(sid, {}).get(name)
                    if not before or not data["total"] or not before.get("total"):
                        continue
                    was = before["passed"] / before["total"]
                    now = data["passed"] / data["total"]
                    if abs(now - was) >= 0.01:
                        moves.append(f"  {sid} / {name}: {was:.0%} → {now:.0%}")
            print("\n".join(moves) if moves else "  通过率没有变化。")
    (RESULTS_DIR / f"{stamp}.json").write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


async def _main() -> int:
    argv = sys.argv[1:]
    args = _scenario_args(argv)
    raw_only = "--raw" in argv
    runs = 1 if raw_only else _int_flag(argv, "--runs", DEFAULT_RUNS)
    picked = [s for s in SCENARIOS if not args or s["id"] in args]
    if not picked:
        raise SystemExit(f"没有匹配的场景。可用: {[s['id'] for s in SCENARIOS]}")

    judge = None if raw_only else _judge_model()
    # 场景和轮次彼此独立，全放出去并发；判官那头由 `_slots()` 统一限流
    planned = [(scenario, index) for scenario in picked for index in range(runs)]
    finished = await asyncio.gather(*(_run_once(scenario, judge) for scenario, _ in planned))

    runs_by_scenario: dict[str, list[dict]] = {scenario["id"]: [] for scenario in picked}
    for (scenario, _), data in zip(planned, finished):
        runs_by_scenario[scenario["id"]].append(data)

    # 先把每一段对话落盘，再打汇总。--raw 那条路也要存 —— 它存在的意义就是"只看对话"。
    stamp = time.strftime("%Y%m%d-%H%M%S")
    _save_transcripts(picked, runs_by_scenario, stamp)

    if raw_only:
        for scenario in picked:
            _print_transcript(scenario, runs_by_scenario[scenario["id"]][0]["turns"])
        print(f"\n对话原文（全部 {len(planned)} 段）：{RESULTS_DIR / f'{stamp}-transcripts.md'}")
        return 0

    print(f"\n跑 {len(picked)} 个场景 × {runs} 轮"
          f"（同一场景每轮都是一次独立的对话 —— 回复是采样出来的，一轮不算数）")
    _print_transcript(picked[0], runs_by_scenario[picked[0]["id"]][0]["turns"])

    results = {scenario["id"]: _aggregate(runs_by_scenario[scenario["id"]]) for scenario in picked}
    for scenario in picked:
        _print_aggregate(scenario["id"], results[scenario["id"]])

    unreliable, unmeasured = [], []
    for sid, agg in results.items():
        for name, data in agg.items():
            if not data["total"]:
                unmeasured.append(f"{sid}/{name}")
            elif data["passed"] / data["total"] < MIN_PASS_RATE:
                unreliable.append(f"{sid}/{name} {data['passed']}/{data['total']}")

    print(f"\n{'=' * 78}")
    if unreliable:
        print(f"通过率低于 {MIN_PASS_RATE:.0%} 的（{len(unreliable)} 条）：")
        for item in unreliable:
            print(f"  · {item}")
    if unmeasured:
        print(f"判官没跑成的（{len(unmeasured)} 条）：{'、'.join(unmeasured)}")
    if not unreliable and not unmeasured:
        print("所有判据的通过率都在门槛之上。")

    _save_and_diff(results, stamp)
    print(f"\n对话原文（全部 {len(planned)} 段）：{RESULTS_DIR / f'{stamp}-transcripts.md'}")
    return 1 if (unreliable or unmeasured) else 0


def main() -> int:
    # 这个脚本里到处是中文。输出重定向到文件时 Windows 按控制台代码页（GBK）写，
    # 读日志就是一串乱码 —— 而"看不懂日志"正是排查上面那个编码崩溃时最费时间的地方。
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())

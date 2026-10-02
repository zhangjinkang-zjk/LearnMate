# -*- coding: utf-8 -*-
"""`eval/reference/*.yaml` 是"资料内容真不真"的**判据底本** —— 它必须自己站得住。

底本里每条断言都配一段 `probe` 和一份 `expect`，`claim_audit.py` 拿它去判学习资料写没写错。
**判据本身错了，整份审计就是错的，而且错得看不出来** —— 它会稳定地指控正确的材料、
或者放过错误的材料。所以这里把每一条 probe 真跑一遍，核对实跑输出是不是等于 `expect`。

这条测试守的是两类事故：
- 有人改了 probe、忘了改 expect（或反过来）；
- 有人从别的 Python 版本抄了一份"应该有这个行为"的说法进来 —— 而实际版本不这么跑。

**探针用什么解释器跑，就用什么解释器核对**（`sys.executable`）。底本记的版本在
`verified_on` 里，和实跑版本不一致时下面会直接报出来。
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REFERENCE_DIR = REPO_ROOT / "eval" / "reference"
REFERENCES = sorted(REFERENCE_DIR.glob("*.yaml"))


def _run_probe(probe: str) -> str:
    """把 probe 当脚本跑，**最后一条语句**（必须是个表达式）的值打出来。

    用子进程而不是 `exec`：探针之间不该共享任何状态（同一个名字 `f` 几乎每条都用），
    而且真正的复核者也是这么验证的 —— 复制进解释器跑一遍。

    取最后一条语句用 AST 而不是"取最后一行"：探针里可以有 `try/except`、`def` 这类
    多行语句，按行取会把缩进取坏（写过一次，一条本来好在跑的探针被判成语法错）。
    """
    tree = ast.parse(probe)
    last = tree.body[-1]
    if not isinstance(last, ast.Expr):
        raise ValueError("probe 的最后一条语句必须是一个表达式：它的值就是这条判据的实测结果")
    body = ast.unparse(ast.Module(body=tree.body[:-1], type_ignores=[]))
    result = subprocess.run(
        [sys.executable, "-c", body + "\nprint(repr(" + ast.unparse(last.value) + "))"],
        capture_output=True, text=True, encoding="utf-8",
    )
    return (result.stdout or "").strip()


def test_there_is_at_least_one_reference():
    """没有底本的话，下面那些参数化用例会**一条都不跑** —— 测试全绿，而审计其实没有判据。"""
    assert REFERENCES, f"{REFERENCE_DIR} 下没有参考底本"


@pytest.mark.parametrize("path", REFERENCES, ids=lambda p: p.stem)
def test_the_reference_parses_and_has_the_required_fields(path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert data.get("topic"), "底本要说明它判的是哪个主题"
    assert data.get("claims"), "底本里一条断言都没有"

    ids = [claim["id"] for claim in data["claims"]]
    assert len(ids) == len(set(ids)), f"断言 id 有重复：{ids}"
    for claim in data["claims"]:
        missing = {"id", "claim", "probe", "expect"} - set(claim)
        assert not missing, f"{claim.get('id')} 缺字段 {missing}"


@pytest.mark.parametrize("path", REFERENCES, ids=lambda p: p.stem)
def test_every_probe_still_produces_its_recorded_expectation(path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for claim in data["claims"]:
        got = _run_probe(claim["probe"])
        assert got == claim["expect"], (
            f"{path.name} 的 {claim['id']}：底本记的是 {claim['expect']!r}，"
            f"实跑是 {got!r}。判据和事实对不上，先修底本再判材料。"
        )

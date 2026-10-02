# -*- coding: utf-8 -*-
"""工具参数出错时，错误应该**回到模型手里**，而不是把学生那条流打断。

LangChain 的默认是抛出去：`BaseTool.run` 里 `handle_validation_error` 为空时，
pydantic 的校验错误一路穿过 AgentExecutor，学生看到对话断在半句上；而模型**看不见**
这件事 —— 它只知道流没了，下一轮把同一个参数原样再发一遍。

这个文件钉住 `_build_agent` 里那个开关：交给执行器的每个工具都必须打开它。
"""
import pytest

from backend.src.ai_core.brain import Brain, _report_tool_error


def _brain(tool_names: set[str]) -> Brain:
    """和 `classroom_chat` 里一样地建一个教练 agent，只是不读库、不装 action tools。"""
    brain = Brain(user_id=0, chat_group_id=0, agent_id=None)
    brain._agent_persona = "你是一个教练。"
    brain._agent_tool_names = tool_names
    brain._agent_memory_text = ""
    brain._agent_config_loaded = True
    brain._build_agent(action_tools=[])
    return brain


def test_every_tool_given_to_the_executor_reports_its_errors():
    brain = _brain({"web_search", "read_web_page", "fetch_framework_docs"})

    tools = brain._raw_executor.tools
    assert tools, "执行器里一个工具都没有，这条测试就没意义了"
    for tool in tools:
        assert tool.handle_validation_error, f"{tool.name} 的参数校验错误还是会抛出去"
        assert tool.handle_tool_error, f"{tool.name} 的 ToolException 还是会抛出去"


@pytest.mark.asyncio
async def test_a_bad_argument_comes_back_as_a_message_the_model_can_act_on():
    """真跑一次：给 `web_search` 一个它收不下的 query。

    以前这里抛异常、整条流就断在这儿。现在它必须**有返回值**，而且那句话要告诉模型
    下一步怎么办 —— 只说"参数不对"，模型经常会原样再发一遍。
    """
    tool = _brain({"web_search"})._raw_executor.tools[0]

    reply = await tool.ainvoke({"query": {"不是": "字符串"}})

    assert isinstance(reply, str)
    assert "没有执行" in reply
    assert "原样再发一遍" in reply


def test_the_message_is_written_for_the_model_not_for_a_log():
    message = _report_tool_error(ValueError("boom"))

    assert "boom" in message                    # 原因要带上，否则它无从改起
    assert "再调一次" in message

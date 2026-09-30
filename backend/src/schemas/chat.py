from typing import Optional
from pydantic import BaseModel, Field


class PageContext(BaseModel):
    """用户此刻停在界面的哪一页。

    **只收标识，不收任何正文。** 客户端是唯一知道"屏幕上是哪一页"的一方，所以标识
    只能由它给；但任务名、节点名这类服务端有权威副本的字段一律按 id 重查 ——
    否则学生改一下自己的请求体，就能往上下文里塞一份伪造的"任务要求"去操纵模型。
    （信任规则与课堂那条一致，见 service/path/classroom_chat.py 的注释。）

    `path_id` 故意不收：服务端用该用户**自己的当前路径**，节点必须在这条路径里，
    于是客户端传的 `node_id` 无法越权到别人的路径上。
    """

    page: str = Field(default="", max_length=32, description="页面标识，服务端按白名单取中文名")
    node_id: Optional[int] = Field(default=None, gt=0, description="用户正在看的路径节点 ID")
    task_id: str = Field(default="", max_length=128, description="进阶实践任务 ID（= 会话的 task_key）")


class CreateNewHistory(BaseModel):
    """新建对话"""
    user_req: str = Field(description="用户提问内容")
    agent_id: Optional[int] = Field(default=None, description="自建智能体ID")
    page_context: Optional[PageContext] = Field(default=None, description="用户当前所在页面")


class CreateMsgIntoHistory(BaseModel):
    """向已有对话追加消息"""
    chat_group_id: int = Field(description="对话组 ID")
    user_req: str = Field(description="用户提问内容")
    agent_id: Optional[int] = Field(default=None, description="自建智能体ID")
    page_context: Optional[PageContext] = Field(default=None, description="用户当前所在页面")


class StreamNewHistory(BaseModel):
    """流式新建对话"""
    user_req: str = Field(description="用户提问内容")
    agent_id: Optional[int] = Field(default=None, description="自建智能体ID")
    page_context: Optional[PageContext] = Field(default=None, description="用户当前所在页面")


class StreamMsgIntoHistory(BaseModel):
    """流式追加消息到已有对话"""
    chat_group_id: int = Field(description="对话组 ID")
    user_req: str = Field(description="用户提问内容")
    agent_id: Optional[int] = Field(default=None, description="自建智能体ID")
    page_context: Optional[PageContext] = Field(default=None, description="用户当前所在页面")

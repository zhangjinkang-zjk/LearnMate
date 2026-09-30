import { streamJsonEvents } from './sseClient'

// 这两个接口的可选参数走对象承载（AGENTS §2：参数超过 3 个就不再用位置参数传）。
// `pageContext` 是"用户此刻在哪一页"的标识，由 entities/learning/currentPageContext
// 提供；没有页面时是 null，后端就是不认识这个页面 —— 不是错误。
export const chatApi = {
  streamNewHistory(userReq, { onEvent, signal, pageContext = null } = {}) {
    return streamJsonEvents('/ai_chat/stream_new_history', {
      user_req: userReq,
      page_context: pageContext,
    }, onEvent, { signal })
  },

  streamMessage(chatGroupId, userReq, { onEvent, signal, pageContext = null } = {}) {
    return streamJsonEvents('/ai_chat/stream_msg_into_history', {
      chat_group_id: Number(chatGroupId),
      user_req: userReq,
      page_context: pageContext,
    }, onEvent, { signal })
  },

  generateResource(topic, chatGroupId, onEvent, signal) {
    return streamJsonEvents('/resource/generate/stream', {
      topic,
      resource_types: ['document', 'mindmap'],
      chat_group_id: Number(chatGroupId) || 0,
      bind_chat_history: Boolean(chatGroupId),
      save_to_chat_history: true,
    }, onEvent, { signal })
  },
}

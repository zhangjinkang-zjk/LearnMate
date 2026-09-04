import { streamJsonEvents } from './sseClient'

export const chatApi = {
  streamNewHistory(userReq, onEvent, signal) {
    return streamJsonEvents('/ai_chat/stream_new_history', { user_req: userReq }, onEvent, { signal })
  },

  streamMessage(chatGroupId, userReq, onEvent, signal) {
    return streamJsonEvents('/ai_chat/stream_msg_into_history', {
      chat_group_id: Number(chatGroupId),
      user_req: userReq,
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

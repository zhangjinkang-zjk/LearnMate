import httpClient from './httpClient'
import { streamJsonEvents } from './sseClient'

function unwrap(response) {
  const payload = response?.data
  if (payload?.code && payload.code !== 200) {
    const error = new Error(payload.msg || '请求失败')
    error.response = { status: payload.code, data: { detail: error.message } }
    throw error
  }
  return payload?.data ?? payload
}

export const fundamentalsApi = {
  async getCurrentPath() {
    try {
      return unwrap(await httpClient.get('/learning_path/current'))
    } catch (error) {
      if (error.response?.status === 404) return null
      throw error
    }
  },

  async getNode(pathId, nodeId) {
    return unwrap(await httpClient.get(`/path/${pathId}/node/${nodeId}`))
  },

  async getResource(resourceId) {
    return unwrap(await httpClient.get(`/resource/${resourceId}`))
  },

  async markResourceRead(resourceId, durationSeconds = 0) {
    return unwrap(await httpClient.post(`/study/resource/${resourceId}/mark-read`, null, {
      params: { duration_seconds: Math.max(0, Math.round(durationSeconds)) },
    }))
  },

  generateResources(pathId, nodeId, onEvent, signal) {
    return streamJsonEvents(
      `/path/${pathId}/node/${nodeId}/generate-resources/stream`,
      { resource_types: ['document', 'mindmap'], background: false },
      onEvent,
      { signal },
    )
  },

  generateQuiz(pathId, nodeId, onEvent, signal) {
    return streamJsonEvents(
      `/path/${pathId}/node/${nodeId}/generate-quiz/stream`,
      undefined,
      onEvent,
      { signal },
    )
  },

  async getQuizSession(sessionId) {
    return unwrap(await httpClient.get(`/exam/session/${sessionId}`))
  },

  async completeNode(nodeId, sessionId, answers) {
    return unwrap(await httpClient.post(`/learning_path/nodes/${nodeId}/complete`, {
      session_id: sessionId,
      answers,
    }))
  },

  streamAssistantReply(payload, onEvent, signal) {
    return streamJsonEvents('/path/classroom/chat', payload, onEvent, { signal })
  },
}

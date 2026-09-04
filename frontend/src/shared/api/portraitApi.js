import httpClient from './httpClient'

const unwrap = (response) => response?.data?.data ?? response?.data ?? response

export const getNextPortraitInterviewQuestion = async (payload) => {
  const response = await httpClient.post('/ai_portrait/interview/next', payload)
  return unwrap(response)
}

export const initPortraitFromDialogue = async (payload) => {
  const response = await httpClient.post('/ai_portrait/init_from_dialogue', payload)
  return unwrap(response)
}

export const readPortrait = async () => {
  const response = await httpClient.get('/ai_portrait/read_portrait')
  return unwrap(response)
}

export const readPortraitRadar = async () => {
  const response = await httpClient.get('/ai_portrait/radar')
  return unwrap(response)
}

import httpClient from './httpClient'

export const learningApi = {
  getOverview: () => httpClient.get('/study/overview'),
  getCurrentPath: () => httpClient.get('/learning_path/current'),
  // 「路径到了没有」用的轻量探询：两次读库。别拿 /study/overview 干这件事 —— 它每次都要
  // 重算六维雷达，几秒一次的轮询会把服务端压垮（见 PortraitSummaryPage 的等路径逻辑）。
  listPaths: () => httpClient.get('/path/list'),
  generatePath: (subject, forceRegenerate = false) => httpClient.post('/path/generate', { subject, difficulty: 'medium', node_count: 0, force_regenerate: forceRegenerate }),
  regeneratePath: (pathId) => httpClient.post('/path/regenerate', { path_id: pathId }),
  // 这个请求现在**只负责排队**：节点生成已经不在它里面了（接口几百毫秒就返回
  // generation_status: "pending"，见 PortraitSummaryPage 的等路径逻辑）。留下的 5 分钟是给
  // 路径拆解（方向→科目）那次模型调用的余量 —— 缓存命中时它只是纯读库，落空时才是一次
  // 二十几秒的调用。不改变普通接口的 15 秒超时。
  generatePathsFromDirection: (direction = '', goal = '', forceRegenerate = false) => httpClient.post('/path/generate-from-direction', { direction, goal, subject_limit: 4, difficulty: 'medium', node_count: 0, force_regenerate: forceRegenerate }, { timeout: 300000 }),
  getStudyStats: () => httpClient.get('/study/stats'),
  getPathStats: () => httpClient.get('/study/path-stats'),
  getMastery: () => httpClient.get('/exam/mastery'),
  getLearningGuidance: () => httpClient.get('/study/learning-guidance'),
  getExamWeekly: () => httpClient.get('/study/exam-weekly'),
  // 诊断走 diagnosisApi（/learning/diagnosis/start|answer|…/stream）。
  // 这里曾有一个 POST /learning/diagnosis，但后端只注册了子路径，调用必 404。
}

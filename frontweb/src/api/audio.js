import request from '@/utils/request'

/**
 * 角色声音体系 (VoiceProfile)、整剧音乐圣经 (MusicBible) 与分镜配乐 (MusicCue) API
 * 对应后端 /api/v1/platform/audio 及 /api/v1/audio 契约
 */
export const audioAPI = {
  // 单分镜/单段文本 TTS 语音提取
  extract(data) {
    return request.post('/audio/extract', data)
  },
  // 批量分镜 TTS 提取
  extractBatch(data) {
    return request.post('/audio/extract/batch', data)
  },
  // 查询短剧角色声音档案列表
  listVoiceProfiles(dramaId) {
    return request.get('/platform/audio/voice-profiles', { params: { drama_id: dramaId } })
  },
  // 自动分析角色人设生成 VoiceProfile
  generateVoiceProfiles(data) {
    return request.post('/platform/audio/voice-profiles/generate', data)
  },
  // 获取整剧 Music Bible 音乐设计规范
  getMusicBible(dramaId) {
    return request.get('/platform/audio/music-bible', { params: { drama_id: dramaId } })
  },
  // 生成整剧 Music Bible
  generateMusicBible(data) {
    return request.post('/platform/audio/music-bible/generate', data)
  },
  // 查询分镜 Music & SFX Cues
  listMusicCues(params) {
    return request.get('/platform/audio/music-cues', { params })
  },
  // 一键生成整剧声音与分镜音乐全套设计
  generateAudioDesign(data) {
    return request.post('/platform/audio/design/generate', data)
  },
  // 更新单个角色声音档案（音色、语速、音高、试听参考音频）
  updateVoiceProfile(id, data) {
    return request.put(`/platform/audio/voice-profiles/${id}`, data)
  },
  // AI 配乐/音乐生成（对接 Suno/Udio/本地检索）
  generateMusicTrack(data) {
    return request.post('/platform/audio/music/generate', data)
  },
  // 多轨智能混音与响度调平
  normalizeAndMixAudio(data) {
    return request.post('/platform/audio/mix-ducking', data)
  },
}


/**
 * Pinia 全局剧本与影视创作状态管理 Store (useFilmStore)
 * 
 * 【设计定位与架构职责】
 * 1. 项目与剧集状态（Drama & Episode Context）：
 *    - 维持当前选中的剧本项目 (drama) 及当前活跃单集 (currentEpisode)。
 *    - 维护剧本大纲创意输入 (storyInput) 与当前集完整剧本文本 (scriptContent)。
 * 2. 分集派生资产计算（Derived Assets）：
 *    - characters/scenes/props/storyboards 计算属性基于当前活跃集动态响应，隔离不同集之间的视觉资产展示。
 * 3. 跨集视频合成状态追踪（Multi-Episode Video Merge Progress）：
 *    - 使用复合键 `dramaId:episodeId` 隔离多集视频合成进度 (progress) 与状态 (status)，确保剧集切换不丢失后台渲染状态。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

/**
 * 生成剧集视频合成状态唯一缓存键
 * @param {number|string|null} dramaId - 项目ID
 * @param {number|string|null} episodeId - 单集ID
 * @returns {string|null} 形如 "1001:2" 的唯一复合键
 */
function episodeVideoKey(dramaId, episodeId) {
  if (dramaId == null || episodeId == null) return null
  return `${dramaId}:${episodeId}`
}

export const useFilmStore = defineStore('film', () => {
  // 当前加载的短剧项目详情
  const drama = ref(null)
  // 当前处于选中/编辑状态的单集
  const currentEpisode = ref(null)
  // 剧本创作初始故事点子/大纲输入
  const storyInput = ref('')
  // 当前集正在编辑的完整剧本内容
  const scriptContent = ref('')
  // 目标视频渲染输出分辨率（480p / 720p / 1080p）
  const videoResolution = ref('480p')
  /** 
   * 按 dramaId:episodeId 存储合成视频进度与状态
   * 数据结构：{ [key: string]: { status: 'idle'|'processing'|'completed'|'failed', progress: number } }
   */
  const videoStateByKey = ref({})

  // 计算属性：当前项目 ID
  const dramaId = computed(() => drama.value?.id ?? null)
  // 计算属性：角色/道具/场景/分镜默认关联本集资源（随 currentEpisode 切换响应式刷新）
  const characters = computed(() => currentEpisode.value?.characters ?? [])
  const scenes = computed(() => currentEpisode.value?.scenes ?? [])
  const props = computed(() => currentEpisode.value?.props ?? [])
  const storyboards = computed(() => currentEpisode.value?.storyboards ?? [])

  // 当前活跃集的视频合成键
  const currentVideoKey = computed(() =>
    episodeVideoKey(drama.value?.id ?? null, currentEpisode.value?.id ?? null)
  )

  // 当前活跃集的视频合成进度
  const videoProgress = computed(() => {
    const k = currentVideoKey.value
    if (!k) return 0
    return videoStateByKey.value[k]?.progress ?? 0
  })

  // 当前活跃集的视频合成状态
  const videoStatus = computed(() => {
    const k = currentVideoKey.value
    if (!k) return 'idle'
    return videoStateByKey.value[k]?.status ?? 'idle'
  })

  /**
   * 内部方法：确保指定 key 的视频状态对象存在
   */
  function _ensureVideoState(key) {
    if (!key) return null
    if (!videoStateByKey.value[key]) {
      videoStateByKey.value = {
        ...videoStateByKey.value,
        [key]: { status: 'idle', progress: 0 },
      }
    }
    return videoStateByKey.value[key]
  }

  /**
   * 设置当前项目对象
   */
  function setDrama(d) {
    drama.value = d
  }

  /**
   * 设置当前选中的活跃单集
   */
  function setCurrentEpisode(ep) {
    currentEpisode.value = ep
  }

  /**
   * 更新故事创意输入文本
   */
  function setStoryInput(text) {
    storyInput.value = text
  }

  /**
   * 更新当前集剧本文本
   */
  function setScriptContent(text) {
    scriptContent.value = text
  }

  /**
   * 设置指定剧集或当前集的视频合成进度百分比 (0-100)
   */
  function setVideoProgress(p, dId, eId) {
    const key = episodeVideoKey(
      dId ?? drama.value?.id ?? null,
      eId ?? currentEpisode.value?.id ?? null
    )
    if (!key) return
    const prev = _ensureVideoState(key)
    videoStateByKey.value = {
      ...videoStateByKey.value,
      [key]: { ...prev, progress: p },
    }
  }

  /**
   * 设置指定剧集或当前集的视频合成状态
   */
  function setVideoStatus(s, dId, eId) {
    const key = episodeVideoKey(
      dId ?? drama.value?.id ?? null,
      eId ?? currentEpisode.value?.id ?? null
    )
    if (!key) return
    const prev = _ensureVideoState(key)
    videoStateByKey.value = {
      ...videoStateByKey.value,
      [key]: { ...prev, status: s },
    }
  }

  /**
   * 获取指定剧集的视频合成状态
   */
  function getVideoStatus(dId, eId) {
    const key = episodeVideoKey(dId, eId)
    if (!key) return 'idle'
    return videoStateByKey.value[key]?.status ?? 'idle'
  }

  /**
   * 重置当前创作会话上下文（保留持久化的 videoStateByKey 跨剧合成进度）
   */
  function reset() {
    drama.value = null
    currentEpisode.value = null
    storyInput.value = ''
    scriptContent.value = ''
  }

  return {
    drama,
    currentEpisode,
    storyInput,
    scriptContent,
    videoResolution,
    videoStateByKey,
    videoProgress,
    videoStatus,
    dramaId,
    characters,
    scenes,
    props,
    storyboards,
    setDrama,
    setCurrentEpisode,
    setStoryInput,
    setScriptContent,
    setVideoProgress,
    setVideoStatus,
    getVideoStatus,
    reset,
  }
})

/**
 * 画布与分镜工作流执行引擎 (useCanvasWorkflowRunner)
 * 
 * 【架构设计与调度流程】
 * 1. 分镜流水线阶段（Storyboard Pipeline Phases）：
 *    - Image Step: 文生图 / 垫图生图（读取 polished_prompt / image_prompt，锁定画幅比例与画风）。
 *    - Video Step: 图生视频 / 首尾帧生视频（支持 Seedance2/Kling/Jimeng 模式下的首帧尾帧锚定）。
 *    - Audio Step: 对白 TTS 配音与旁白音频抽取生成。
 * 2. 轮询与异步任务协调（Async Task Polling）：
 *    - 封装 pollTaskSimple 轮询后端 `async_tasks`，捕获进度、成功与失败并及时抛出错误。
 * 3. 组批与依赖编排（Workflow Groups Execution）：
 *    - 支持按工作流组 (Group) 拓扑顺序依次或并行执行分镜流水线，提供细粒度生命周期 Hook 回调。
 */
import { taskAPI } from '@/api/task'
import { imagesAPI } from '@/api/images'
import { videosAPI } from '@/api/videos'
import request from '@/utils/request'
import { storyboardImageUrl } from '@/utils/mediaUrl'
import {
  DEFAULT_PIPELINE,
  findStoryboardInDrama,
  getDramaGenerationOptions,
  toAbsoluteMediaUrl,
} from '@/utils/canvasWorkflow'
import { dramaUsesFirstLastFrame, sbVideoFirstLastUrls } from '@/utils/storyboardMedia'

/**
 * 轮询异步任务状态，直到完成、失败或超时
 * @param {string} taskId - 后端异步任务唯一ID
 * @param {object} options - 轮询控制选项 (maxAttempts: 最大尝试次数, interval: 间隔毫秒)
 * @returns {Promise<{status: string, result?: any, error?: string}>}
 */
async function pollTaskSimple(taskId, options = {}) {
  if (!taskId) return { status: 'failed', error: '缺少 task_id' }
  const maxAttempts = options.maxAttempts ?? 450
  const interval = options.interval ?? 2000
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, interval))
    try {
      const t = await taskAPI.get(taskId)
      if (t.status === 'completed') return { status: 'completed', result: t.result }
      if (t.status === 'failed') {
        return { status: 'failed', error: t.error?.message || t.error || '任务失败' }
      }
    } catch (e) {
      if (i === maxAttempts - 1) return { status: 'failed', error: e.message || '轮询失败' }
    }
  }
  return { status: 'timeout', error: '任务超时' }
}

/**
 * 执行单分镜生图步骤 (Text-to-Image / Image-to-Image)
 * @param {object} drama - 短剧主对象
 * @param {object} sb - 当前分镜对象
 * @param {object} genOpts - 全局生成参数 (style, aspectRatio 等)
 */
export async function runImageStep(drama, sb, genOpts) {
  const prompt = sb.polished_prompt || sb.image_prompt || sb.description || sb.action || ''
  if (!prompt.trim()) throw new Error(`分镜 #${sb.storyboard_number ?? sb.id} 缺少图片提示词`)
  const res = await imagesAPI.create({
    storyboard_id: sb.id,
    drama_id: drama.id,
    prompt,
    style: genOpts.style || undefined,
    aspect_ratio: genOpts.aspectRatio,
  })
  if (res?.task_id) {
    const polled = await pollTaskSimple(res.task_id)
    if (polled.status !== 'completed') throw new Error(polled.error || '分镜图生成失败')
  }
}

/**
 * 执行单分镜生视频步骤 (Image-to-Video / First-Last-Frame Video)
 * @param {object} drama - 短剧主对象
 * @param {object} sb - 当前分镜对象
 * @param {object} genOpts - 视频生成选项 (videoResolution, aspectRatio, imagesBySbId 等)
 */
export async function runVideoStep(drama, sb, genOpts) {
  const useFirstLast = dramaUsesFirstLastFrame(drama)
  const imagesBySbId = genOpts?.imagesBySbId || {}
  const { first, last } = sbVideoFirstLastUrls(sb, imagesBySbId, useFirstLast)
  const imgPath = first || storyboardImageUrl(sb)
  if (!imgPath && !sb.video_prompt && !last) {
    throw new Error(`分镜 #${sb.storyboard_number ?? sb.id} 缺少分镜图，无法生成视频`)
  }
  const absoluteFirst = toAbsoluteMediaUrl(imgPath)
  const absoluteLast = last ? toAbsoluteMediaUrl(last) : undefined
  const prompt = sb.video_prompt || sb.polished_prompt || sb.image_prompt || sb.description || ''
  const res = await videosAPI.create({
    drama_id: drama.id,
    storyboard_id: sb.id,
    prompt,
    image_url: absoluteFirst || undefined,
    first_frame_url: absoluteFirst || undefined,
    last_frame_url: absoluteLast,
    style: genOpts.style || undefined,
    aspect_ratio: genOpts.aspectRatio,
    resolution: genOpts.videoResolution || undefined,
    duration: sb.duration || undefined,
  })
  if (res?.task_id) {
    const polled = await pollTaskSimple(res.task_id)
    if (polled.status !== 'completed') throw new Error(polled.error || '视频生成失败')
  }
}

/**
 * 执行单分镜对白 TTS 音频生成步骤
 * @param {object} sb - 分镜对象
 */
export async function runAudioStep(sb) {
  const text = (sb.dialogue || '').trim()
  if (!text) return { skipped: true, reason: '无对白' }
  await request.post('/audio/extract', {
    storyboard_id: sb.id,
    text,
    tts_kind: 'dialogue',
  })
  return { skipped: false }
}

/**
 * 对单个分镜按 pipeline 顺序执行生成流水线 (image -> video -> audio)
 * @param {object} drama - 短剧主对象
 * @param {number|string} storyboardId - 分镜ID
 * @param {('image'|'video'|'audio')[]} pipeline - 步骤列表
 * @param {object} hooks - 生命周期回调
 */
export async function runStoryboardPipeline(drama, storyboardId, pipeline, hooks = {}) {
  const found = findStoryboardInDrama(drama, storyboardId)
  if (!found) throw new Error(`找不到分镜 ${storyboardId}`)
  let { storyboard: sb } = found
  const genOpts = {
    ...getDramaGenerationOptions(drama),
    ...(hooks.generationOptions || {}),
  }
  const steps = pipeline?.length ? pipeline : DEFAULT_PIPELINE
  const results = []

  for (const step of steps) {
    hooks.onStepStart?.({ storyboardId, step, sb })
    try {
      if (step === 'image') {
        await runImageStep(drama, sb, genOpts)
        if (hooks.reloadStoryboard) {
          sb = (await hooks.reloadStoryboard(storyboardId)) || sb
        }
      } else if (step === 'video') {
        await runVideoStep(drama, sb, genOpts)
        if (hooks.reloadStoryboard) {
          sb = (await hooks.reloadStoryboard(storyboardId)) || sb
        }
      } else if (step === 'audio') {
        const audioRes = await runAudioStep(sb)
        results.push({ step, ...audioRes })
      }
      hooks.onStepComplete?.({ storyboardId, step, sb })
    } catch (err) {
      hooks.onStepError?.({ storyboardId, step, error: err })
      throw err
    }
  }
  return results
}

/**
 * 按工作流组顺序批量执行流水线（组内分镜按 storyboard_ids 顺序依次调度）
 * @param {object} drama - 短剧主对象
 * @param {object} group - 工作流分组对象 ({ id, pipeline, storyboard_ids })
 * @param {object} hooks - 回调函数集合
 */
export async function runWorkflowGroup(drama, group, hooks = {}) {
  const pipeline = group.pipeline || DEFAULT_PIPELINE
  const ids = group.storyboard_ids || []
  const summary = { groupId: group.id, ok: [], failed: [] }

  for (const sbId of ids) {
    hooks.onStoryboardStart?.({ group, storyboardId: sbId })
    try {
      await runStoryboardPipeline(drama, sbId, pipeline, hooks)
      summary.ok.push(sbId)
      hooks.onStoryboardComplete?.({ group, storyboardId: sbId })
    } catch (err) {
      summary.failed.push({ storyboardId: sbId, error: err.message || String(err) })
      hooks.onStoryboardError?.({ group, storyboardId: sbId, error: err })
      if (hooks.stopOnError) break
    }
  }
  return summary
}

/**
 * Node 契约探针：用内存 SQLite 跑真实路由模块，暴露与 Python 版相同的 HTTP 接口。
 *
 * 只读加载 backend-node 的 src 路由/服务/migrations，**不触碰 backend-node 任何数据文件**
 * （数据库为 :memory:），仅用于对拍 Python 版响应契约。
 *
 * 用法：node tools/node_probe.js <port>
 */
const path = require('path');
const fs = require('fs');
const Database = require(path.join(__dirname, '..', '..', 'backend-node', 'node_modules', 'better-sqlite3'));
const express = require(path.join(__dirname, '..', '..', 'backend-node', 'node_modules', 'express'));

const NODE_SRC = path.join(__dirname, '..', '..', 'backend-node', 'src');
const MIGRATIONS = path.join(__dirname, '..', '..', 'backend-node', 'migrations');

const port = Number(process.argv[2] || 5699);

const db = new Database(':memory:');
// 复用 Node 自身的迁移 + 兜底补列逻辑（保证库结构与真实运行完全一致）
const { runMigrationsAndEnsure } = require(path.join(NODE_SRC, 'db', 'migrate.js'));
runMigrationsAndEnsure(db);
void MIGRATIONS;

// 极简 logger（避免 winston 写文件）
const log = {
  info: () => {},
  warn: () => {},
  error: () => {},
  debug: () => {},
};

const promptOverrides = require(path.join(NODE_SRC, 'routes', 'promptOverrides'));
const sceneModelMap = require(path.join(NODE_SRC, 'routes', 'sceneModelMap'));
const characterLibrary = require(path.join(NODE_SRC, 'routes', 'characterLibrary'));
const sceneLibrary = require(path.join(NODE_SRC, 'routes', 'sceneLibrary'));
const propLibrary = require(path.join(NODE_SRC, 'routes', 'propLibrary'));
const drama = require(path.join(NODE_SRC, 'routes', 'drama'));
const aiConfig = require(path.join(NODE_SRC, 'routes', 'aiConfig'));
const characters = require(path.join(NODE_SRC, 'routes', 'characters'));
const scenes = require(path.join(NODE_SRC, 'routes', 'scenes'));
const prop = require(path.join(NODE_SRC, 'routes', 'prop'));
const storyboards = require(path.join(NODE_SRC, 'routes', 'storyboards'));
const stub = require(path.join(NODE_SRC, 'routes', 'stub'));
const task = require(path.join(NODE_SRC, 'routes', 'task'));
const assets = require(path.join(NODE_SRC, 'routes', 'assets'));
const uploadModule = require(path.join(NODE_SRC, 'routes', 'upload'));
const audio = require(path.join(NODE_SRC, 'routes', 'audio'));
const images = require(path.join(NODE_SRC, 'routes', 'images'));
const videos = require(path.join(NODE_SRC, 'routes', 'videos'));
const videoMerges = require(path.join(NODE_SRC, 'routes', 'videoMerges'));
const response = require(path.join(NODE_SRC, 'response'));

// storage.base_url 与 vendor_lock 段对齐 python-backend/configs/config.yaml，
// 便于 /ai-configs/vendor-lock 与 /upload/image（url 拼接）对拍
const cfg = {
  app: { language: 'zh' },
  storage: { base_url: 'http://localhost:5679/static', local_path: './data/storage' },
  vendor_lock: { enabled: false, config_file: 'ai-configs-qudao.json' },
};

const po = promptOverrides.routes(db, log);  // 该模块导出为 { routes, getPromptDefinitions }
const smm = sceneModelMap(db, log);
const cl = characterLibrary(db, cfg, log);
const sl = sceneLibrary(db, cfg, log);
const pl = propLibrary(db, cfg, log);
const dr = drama(db, cfg, log);
const ac = aiConfig(db, log, cfg);
const ch = characters(db, cfg, log, null);
const sc = scenes(db, log, cfg);
const pr = prop(db, log, cfg);
const sb = storyboards(db, log, cfg);
const sbStub = stub(db, cfg, log);
const tk = task(db, log);
const as = assets(db, log);
const up = uploadModule.routes(cfg, log, db);
const au = audio(db, log, cfg);
const im = images(db, cfg, log);
const vd = videos(db, log);
const vm = videoMerges(db, log);

const app = express();
app.use(express.json());

const r = app;
r.get('/api/v1/settings/prompts', po.list);
r.put('/api/v1/settings/prompts/:key', po.update);
r.delete('/api/v1/settings/prompts/:key', po.reset);

r.get('/api/v1/scene-model-map', smm.list);
r.post('/api/v1/scene-model-map', smm.create);
r.get('/api/v1/scene-model-map/:key', smm.get);
r.put('/api/v1/scene-model-map/:key', smm.update);
r.delete('/api/v1/scene-model-map/:key', smm.delete);

r.get('/api/v1/character-library', cl.list);
r.post('/api/v1/character-library', cl.create);
r.get('/api/v1/character-library/:id', cl.get);
r.put('/api/v1/character-library/:id', cl.update);
r.delete('/api/v1/character-library/:id', cl.delete);

r.get('/api/v1/scene-library', sl.list);
r.post('/api/v1/scene-library', sl.create);
r.get('/api/v1/scene-library/:id', sl.get);
r.put('/api/v1/scene-library/:id', sl.update);
r.delete('/api/v1/scene-library/:id', sl.delete);

r.get('/api/v1/prop-library', pl.list);
r.post('/api/v1/prop-library', pl.create);
r.get('/api/v1/prop-library/:id', pl.get);
r.put('/api/v1/prop-library/:id', pl.update);
r.delete('/api/v1/prop-library/:id', pl.delete);

// dramas（仅 P2 已翻译端点，顺序与 Python 端一致：stats 在 /:id 之前）
r.get('/api/v1/dramas', dr.listDramas);
r.post('/api/v1/dramas', dr.createDrama);
r.get('/api/v1/dramas/stats', dr.getDramaStats);
r.get('/api/v1/dramas/:id/props', dr.listProps);
r.put('/api/v1/dramas/:id/outline', dr.saveOutline);
r.get('/api/v1/dramas/:id/characters', dr.getCharacters);
r.put('/api/v1/dramas/:id/characters', dr.saveCharacters);
r.put('/api/v1/dramas/:id/episodes', dr.saveEpisodes);
r.put('/api/v1/dramas/:id/progress', dr.saveProgress);
r.put('/api/v1/dramas/:id/canvas-layout', dr.saveCanvasLayout);
r.get('/api/v1/dramas/:id', dr.getDrama);
r.put('/api/v1/dramas/:id', dr.updateDrama);
r.delete('/api/v1/dramas/:id', dr.deleteDrama);

// dramas（P4/P5 合成 / 下载 / 纯 AI 占位 / 示例）
r.get('/api/v1/dramas/:id/episodes/:episode_id/download-video', dr.downloadEpisodeVideo);
r.put('/api/v1/dramas/:id/episodes/:episode_id/finalize', dr.finalizeEpisode);
r.post('/api/v1/dramas/:id/episodes/:episode_id/generate-storyboard', dr.generateStoryboard);
r.get('/api/v1/dramas/examples', dr.listExamples);

// episodes（别名路由组）
r.post('/api/v1/episodes/:episode_id/storyboards', dr.generateStoryboard);
r.post('/api/v1/episodes/:episode_id/props/extract', pr.extractProps);
r.post('/api/v1/episodes/:episode_id/characters/extract', sbStub.episodeCharactersExtract);
r.get('/api/v1/episodes/:episode_id/storyboards', sb.episodeStoryboardsGet);
r.post('/api/v1/episodes/:episode_id/finalize', dr.finalizeEpisode);
r.get('/api/v1/episodes/:episode_id/download', dr.downloadEpisodeVideo);

// generation（角色 / 故事生成，同步部分为纯 DB）
r.post('/api/v1/generation/characters', (req, res) => {
  const characterGenerationService = require(path.join(NODE_SRC, 'services', 'characterGenerationService'));
  try {
    const body = req.body || {};
    if (!body.drama_id) return response.badRequest(res, 'drama_id 必填');
    const taskId = characterGenerationService.generateCharacters(db, cfg, log, body);
    response.success(res, { task_id: taskId, status: 'pending' });
  } catch (err) {
    log.error('generation/characters', { error: err.message });
    response.internalError(res, err.message || '创建任务失败');
  }
});

r.post('/api/v1/generation/story', async (req, res) => {
  const storyGenerationService = require(path.join(NODE_SRC, 'services', 'storyGenerationService'));
  try {
    const body = req.body || {};
    if (body.drama_id) {
      const taskId = storyGenerationService.startStoryGeneration(db, log, body);
      return response.success(res, { task_id: taskId, status: 'pending' });
    }
    const result = await storyGenerationService.generateStory(db, log, body);
    response.success(res, result);
  } catch (err) {
    log.error('generation/story', { error: err.message });
    if (err.message && (err.message.includes('未配置') || err.message.includes('必填') || err.message.includes('不存在'))) {
      return response.badRequest(res, err.message);
    }
    response.internalError(res, err.message || '故事生成失败');
  }
});

// ai-configs（静态路径必须注册在 /:id 之前）
r.get('/api/v1/ai-configs', ac.list);
r.post('/api/v1/ai-configs', ac.create);
r.post('/api/v1/ai-configs/test', ac.testConnection);
r.post('/api/v1/ai-configs/jimeng2-list-assets', ac.listJimeng2MaterialAssets);
r.post('/api/v1/ai-configs/model-ark-asset', ac.modelArkAsset);
r.get('/api/v1/ai-configs/vendor-lock', ac.vendorLock);
r.put('/api/v1/ai-configs/bulk-update-key', ac.bulkUpdateKey);
r.get('/api/v1/ai-configs/:id', ac.get);
r.put('/api/v1/ai-configs/:id', ac.update);
r.delete('/api/v1/ai-configs/:id', ac.delete);

// characters（P2 端点）
r.get('/api/v1/characters/:id', ch.getOne);
r.put('/api/v1/characters/:id', ch.update);
r.delete('/api/v1/characters/:id', ch.delete);
r.put('/api/v1/characters/:id/image-from-library', ch.imageFromLibrary);
r.post('/api/v1/characters/:id/add-to-library', ch.addToLibrary);
r.post('/api/v1/characters/:id/add-to-material-library', ch.addToMaterialLibrary);
r.put('/api/v1/characters/:id/image', ch.putImage);
r.post('/api/v1/characters/:id/extract-anchors', ch.extractAnchors);
r.post('/api/v1/characters/:id/sd2-voice-refresh', ch.sd2VoiceRefresh);

// scenes（P2 端点）
r.get('/api/v1/scenes/:scene_id', sc.getOne);
r.post('/api/v1/scenes', sc.create);
r.put('/api/v1/scenes/:scene_id', sc.update);
r.put('/api/v1/scenes/:scene_id/prompt', sc.updatePrompt);
r.delete('/api/v1/scenes/:scene_id', sc.delete);
r.post('/api/v1/scenes/:scene_id/add-to-library', sc.addToLibrary);
r.post('/api/v1/scenes/:scene_id/add-to-material-library', sc.addToMaterialLibrary);

// props（P2 端点）
r.post('/api/v1/props', pr.createProp);
r.get('/api/v1/props/:id', pr.getPropById);
r.put('/api/v1/props/:id', pr.updateProp);
r.delete('/api/v1/props/:id', pr.deleteProp);
r.post('/api/v1/props/:id/add-to-library', pr.addToLibrary);
r.post('/api/v1/props/:id/add-to-material-library', pr.addToMaterialLibrary);

// storyboards（P2 端点；insert-before 需在 /:id 之前，但路径不同故无冲突）
r.post('/api/v1/storyboards', sb.create);
r.post('/api/v1/storyboards/:id/insert-before', sb.insertBefore);
r.post('/api/v1/storyboards/batch-infer-params', sb.batchInferParams);
r.post('/api/v1/storyboards/:id/upscale', sb.upscale);
r.post('/api/v1/storyboards/:id/polish-prompt', sb.polishPrompt);
r.post('/api/v1/storyboards/:id/universal-segment-polish-stream', sb.polishUniversalSegmentStream);
r.post('/api/v1/storyboards/:id/classic-video-prompt-polish-stream', sb.polishClassicVideoPromptStream);
r.post('/api/v1/storyboards/:id/universal-segment-prompt-stream', sb.generateUniversalSegmentStream);
r.post('/api/v1/storyboards/:id/universal-segment-prompt', sb.generateUniversalSegmentPrompt);
r.post('/api/v1/storyboards/episode/:episode_id/generate', sb.episodeStoryboardsGenerate);
r.get('/api/v1/storyboards/:id', sb.getOne);
r.put('/api/v1/storyboards/:id', sb.update);
r.delete('/api/v1/storyboards/:id', sb.delete);
r.get('/api/v1/storyboards/:id/frame-prompts', sb.framePromptsGet);
r.put('/api/v1/storyboards/:id/frame-prompts/:frame_type', sb.framePromptSave);
r.post('/api/v1/storyboards/:id/frame-prompt', sb.framePrompt);
r.post('/api/v1/storyboards/:id/regenerate-layout-description', sb.regenerateLayoutDescription);
r.post('/api/v1/storyboards/:id/rebuild-video-prompt', sb.rebuildVideoPrompt);
r.post('/api/v1/storyboards/:id/split-by-audio', sb.splitByAudio);

// tasks（P2 端点）
r.get('/api/v1/tasks/:task_id', tk.getTaskStatus);
r.post('/api/v1/tasks/:task_id/cancel', tk.cancelTaskStatus);
r.get('/api/v1/tasks', tk.getResourceTasks);

// 对拍专用（非生产端点）：Node 侧没有创建任务的 HTTP 接口，
// 用固定 id / created_at 播种，使两端 /tasks 对拍结果可比较。
r.post('/api/v1/__seed/task', (req, res) => {
  const b = req.body || {};
  const at = b.created_at || new Date().toISOString();
  db.prepare(
    `INSERT INTO async_tasks (id, type, status, progress, message, resource_id, created_at, updated_at)
     VALUES (?, ?, ?, ?, '', ?, ?, ?)`
  ).run(
    b.id,
    b.type || 'test',
    b.status || 'pending',
    b.progress != null ? b.progress : 0,
    b.resource_id || '',
    at,
    at
  );
  res.json({ success: true, data: { id: b.id } });
});

// assets（P2 端点；import 路径须注册在 /:id 之前）
r.get('/api/v1/assets', as.list);
r.post('/api/v1/assets', as.create);
r.post('/api/v1/assets/import/image/:image_gen_id', as.importImage);
r.post('/api/v1/assets/import/video/:video_gen_id', as.importVideo);
r.get('/api/v1/assets/:id', as.get);
r.put('/api/v1/assets/:id', as.update);
r.delete('/api/v1/assets/:id', as.delete);

// 对拍专用（非生产端点）：为 assets 的 import 端点播种生成记录。
// 两端都从空表开始（Python 侧 TRUNCATE 重置自增），故返回的 id 可对齐。
// upload（P2 端点）
r.post('/api/v1/upload/image', uploadModule.multerSingle, up.uploadImage);

// audio（P2 端点）
r.post('/api/v1/audio/extract', au.extract);
r.post('/api/v1/audio/extract/batch', au.extractBatch);

// images（backend-node 的 images 路由实际读写 image_generations 表；具体路径注册在 /:id 之前）
r.get('/api/v1/images', im.list);
r.post('/api/v1/images', im.create);
r.post('/api/v1/images/upload', im.upload);
r.get('/api/v1/images/episode/:episode_id/backgrounds', im.episodeBackgrounds);
r.post('/api/v1/images/episode/:episode_id/backgrounds/extract', im.episodeBackgroundsExtract);
r.post('/api/v1/images/episode/:episode_id/batch', im.episodeBatch);
r.post('/api/v1/images/scene/:scene_id', im.scene);
r.get('/api/v1/images/:id', im.get);
r.delete('/api/v1/images/:id', im.delete);

// videos（同步端点子集；具体路径注册在 /:id 之前）
r.get('/api/v1/videos', vd.list);
r.post('/api/v1/videos', vd.create);
r.post('/api/v1/videos/:id/resume-poll', vd.resumePoll);
r.post('/api/v1/videos/image/:image_gen_id', vd.fromImage);
r.post('/api/v1/videos/episode/:episode_id/batch', vd.episodeBatch);
r.get('/api/v1/videos/:id', vd.get);
r.delete('/api/v1/videos/:id', vd.delete);

// video-merges（同步端点子集）
r.get('/api/v1/video-merges', vm.list);
r.post('/api/v1/video-merges', vm.create);
r.get('/api/v1/video-merges/:merge_id', vm.get);
r.delete('/api/v1/video-merges/:merge_id', vm.delete);

r.post('/api/v1/__seed/episode', (req, res) => {
  const b = req.body || {};
  const eid = b.id;
  let info;
  if (eid != null) {
    info = db
      .prepare('INSERT INTO episodes (id, drama_id, title, episode_number, script_content, description, video_url) VALUES (?, ?, ?, ?, ?, ?, ?)')
      .run(eid, b.drama_id ?? null, b.title || '第1集', b.episode_number ?? 1, b.script_content ?? null, b.description ?? null, b.video_url ?? null);
  } else {
    info = db
      .prepare('INSERT INTO episodes (drama_id, title, episode_number, script_content, description, video_url) VALUES (?, ?, ?, ?, ?, ?)')
      .run(b.drama_id ?? null, b.title || '第1集', b.episode_number ?? 1, b.script_content ?? null, b.description ?? null, b.video_url ?? null);
  }
  res.json({ success: true, data: { id: eid != null ? eid : info.lastInsertRowid } });
});

r.post('/api/v1/__seed/storyboard', (req, res) => {
  const b = req.body || {};
  const sid = b.id;
  let info;
  const dur = b.duration != null ? b.duration : 5;
  if (sid != null) {
    info = db
      .prepare('INSERT INTO storyboards (id, episode_id, dialogue, narration, creation_mode, video_url, local_path, duration, status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
      .run(sid, b.episode_id ?? null, b.dialogue ?? null, b.narration ?? null, b.creation_mode ?? null, b.video_url ?? null, b.local_path ?? null, dur, b.status ?? null, new Date().toISOString());
  } else {
    info = db
      .prepare('INSERT INTO storyboards (episode_id, dialogue, narration, creation_mode, video_url, local_path, duration, status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)')
      .run(b.episode_id ?? null, b.dialogue ?? null, b.narration ?? null, b.creation_mode ?? null, b.video_url ?? null, b.local_path ?? null, dur, b.status ?? null, new Date().toISOString());
  }
  res.json({ success: true, data: { id: sid != null ? sid : info.lastInsertRowid } });
});

// 为 images /get-backgrounds 对拍：写入 scene（带 image_url）+ storyboard（带 scene_id + image_url）
r.post('/api/v1/__seed/scene', (req, res) => {
  const b = req.body || {};
  let sid;
  if (b.id != null) {
    db.prepare('INSERT INTO scenes (id, drama_id, episode_id, image_url, local_path, status) VALUES (?, ?, ?, ?, ?, ?)')
      .run(b.id, b.drama_id ?? 1, b.episode_id ?? null, b.image_url || null, b.local_path ?? null, b.status || 'draft');
    sid = b.id;
  } else {
    const sInfo = db
      .prepare('INSERT INTO scenes (drama_id, episode_id, image_url, local_path, status) VALUES (?, ?, ?, ?, ?)')
      .run(b.drama_id ?? 1, b.episode_id ?? null, b.image_url || null, b.local_path ?? null, b.status || 'draft');
    sid = sInfo.lastInsertRowid;
  }
  let sbId = null;
  if (b.storyboard_image_url !== undefined || b.storyboard_local_path !== undefined) {
    const sbInfo = db
      .prepare('INSERT INTO storyboards (episode_id, scene_id, image_url, local_path) VALUES (?, ?, ?, ?)')
      .run(b.episode_id ?? null, sid, b.storyboard_image_url || null, b.storyboard_local_path ?? null);
    sbId = sbInfo.lastInsertRowid;
  }
  res.json({ success: true, data: { scene_id: sid, storyboard_id: sbId } });
});

// characters 种子：可指定 id / drama_id / image_url / local_path / appearance，用于角色库对拍
r.post('/api/v1/__seed/character', (req, res) => {
  const b = req.body || {};
  if (b.id != null) {
    db.prepare(
      'INSERT INTO characters (id, drama_id, name, image_url, local_path, appearance) VALUES (?, ?, ?, ?, ?, ?)'
    ).run(b.id, b.drama_id ?? 1, b.name || '角色', b.image_url || '', b.local_path ?? null, b.appearance || '外貌描述');
    res.json({ success: true, data: { id: b.id } });
    return;
  }
  const info = db
    .prepare('INSERT INTO characters (drama_id, name, image_url, local_path, appearance) VALUES (?, ?, ?, ?, ?)')
    .run(b.drama_id ?? 1, b.name || '角色', b.image_url || '', b.local_path ?? null, b.appearance || '外貌描述');
  res.json({ success: true, data: { id: info.lastInsertRowid } });
});

// character_libraries 种子：可指定 id，用于 image-from-library 对拍
r.post('/api/v1/__seed/character-library', (req, res) => {
  const b = req.body || {};
  if (b.id != null) {
    db.prepare(
      'INSERT INTO character_libraries (id, drama_id, name, category, image_url, local_path, description, source_type, source_id, created_at, updated_at) '
      + 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
    ).run(
      b.id, b.drama_id ?? null, b.name || '库项', b.category ?? null, b.image_url || '', b.local_path ?? null,
      b.description ?? null, b.source_type || 'character', b.source_id ?? null, new Date().toISOString(), new Date().toISOString()
    );
    res.json({ success: true, data: { id: b.id } });
    return;
  }
  const info = db
    .prepare(
      'INSERT INTO character_libraries (drama_id, name, category, image_url, local_path, description, source_type, source_id, created_at, updated_at) '
      + 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
    )
    .run(
      b.drama_id ?? null, b.name || '库项', b.category ?? null, b.image_url || '', b.local_path ?? null,
      b.description ?? null, b.source_type || 'character', b.source_id ?? null, new Date().toISOString(), new Date().toISOString()
    );
  res.json({ success: true, data: { id: info.lastInsertRowid } });
});
// 故两端 seed 语句不同——此处只填 Node 侧存在的列。
r.post('/api/v1/__seed/tts_config', (req, res) => {
  const b = req.body || {};
  const info = db
    .prepare(
      `INSERT INTO ai_service_configs
       (service_type, provider, name, base_url, api_key, model, default_model,
        priority, is_default, is_active, settings, created_at, updated_at)
       VALUES ('tts', ?, 'TTS', ?, 'sk-tts', '["tts-1"]', ?, 0, 1, ?, ?, ?, ?)`
    )
    .run(
      b.provider || 'openai',
      b.base_url || '',
      b.default_model || 'tts-1',
      b.is_active === undefined ? 1 : b.is_active,
      b.settings ?? null,
      '2026-01-01T00:00:00.000Z',
      '2026-01-01T00:00:00.000Z'
    );
  res.json({ success: true, data: { id: info.lastInsertRowid } });
});

r.post('/api/v1/__seed/drama', (req, res) => {
  const b = req.body || {};
  const at = b.created_at || new Date().toISOString();
  if (b.id != null) {
    db.prepare('INSERT INTO dramas (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)')
      .run(b.id, b.title || '对拍剧', at, at);
    res.json({ success: true, data: { id: b.id } });
    return;
  }
  const info = db
    .prepare('INSERT INTO dramas (title, created_at, updated_at) VALUES (?, ?, ?)')
    .run(b.title || '对拍剧', at, at);
  res.json({ success: true, data: { id: info.lastInsertRowid } });
});

r.post('/api/v1/__seed/image_gen', (req, res) => {
  const b = req.body || {};
  const eid = b.id;
  const ts = b.created_at || new Date().toISOString();
  let newId;
  if (eid != null) {
    db.prepare(
      `INSERT INTO image_generations (id, drama_id, storyboard_id, image_url, local_path, status, frame_type, prompt, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      eid,
      b.drama_id ?? null,
      b.storyboard_id ?? null,
      b.image_url || '',
      b.local_path ?? null,
      b.status ?? null,
      b.frame_type ?? null,
      b.prompt ?? null,
      ts,
      ts
    );
    newId = eid;
  } else {
    const info = db
      .prepare(
        `INSERT INTO image_generations (drama_id, storyboard_id, image_url, local_path, status, frame_type, prompt, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        b.drama_id ?? null,
        b.storyboard_id ?? null,
        b.image_url || '',
        b.local_path ?? null,
        b.status ?? null,
        b.frame_type ?? null,
        b.prompt ?? null,
        ts,
        ts
      );
    newId = info.lastInsertRowid;
  }
  res.json({ success: true, data: { id: newId } });
});

// assets 种子：可指定 id / created_at，用于确定性排序对拍
r.post('/api/v1/__seed/asset', (req, res) => {
  const b = req.body || {};
  const eid = b.id;
  const ts = b.created_at || new Date().toISOString();
  let newId;
  if (eid != null) {
    db.prepare(
      `INSERT INTO assets (id, drama_id, name, type, category, url, local_path, duration, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      eid,
      b.drama_id ?? null,
      b.name || '未命名',
      b.type || 'image',
      b.category ?? null,
      b.url || '',
      b.local_path ?? null,
      b.duration ?? null,
      ts,
      ts
    );
    newId = eid;
  } else {
    const info = db
      .prepare(
        `INSERT INTO assets (drama_id, name, type, category, url, local_path, duration, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        b.drama_id ?? null,
        b.name || '未命名',
        b.type || 'image',
        b.category ?? null,
        b.url || '',
        b.local_path ?? null,
        b.duration ?? null,
        ts,
        ts
      );
    newId = info.lastInsertRowid;
  }
  res.json({ success: true, data: { id: newId } });
});

r.post('/api/v1/__seed/video_gen', (req, res) => {
  const b = req.body || {};
  const info = db
    .prepare(
      `INSERT INTO video_generations (drama_id, video_url, local_path, created_at)
       VALUES (?, ?, ?, ?)`
    )
    .run(b.drama_id ?? null, b.video_url || '', b.local_path ?? null, b.created_at || new Date().toISOString());
  res.json({ success: true, data: { id: info.lastInsertRowid } });
});

// frame_prompts 种子：可指定 id / created_at，用于确定性排序对拍（该端点为 ASC，与其他列表相反）
r.post('/api/v1/__seed/frame_prompt', (req, res) => {
  const b = req.body || {};
  const eid = b.id;
  const ts = b.created_at || new Date().toISOString();
  let newId;
  if (eid != null) {
    db.prepare(
      `INSERT INTO frame_prompts (id, storyboard_id, frame_type, prompt, description, layout, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      eid,
      b.storyboard_id ?? null,
      b.frame_type ?? 'first',
      b.prompt ?? '',
      b.description ?? null,
      b.layout ?? null,
      ts,
      ts
    );
    newId = eid;
  } else {
    const info = db
      .prepare(
        `INSERT INTO frame_prompts (storyboard_id, frame_type, prompt, description, layout, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        b.storyboard_id ?? null,
        b.frame_type ?? 'first',
        b.prompt ?? '',
        b.description ?? null,
        b.layout ?? null,
        ts,
        ts
      );
    newId = info.lastInsertRowid;
  }
  res.json({ success: true, data: { id: newId } });
});

// props 种子：可指定 id / drama_id / episode_id / image_url / local_path，用于 add-to-library 对拍
r.post('/api/v1/__seed/prop', (req, res) => {
  const b = req.body || {};
  const eid = b.id;
  const ts = b.created_at || new Date().toISOString();
  let newId;
  if (eid != null) {
    db.prepare(
      `INSERT INTO props (id, drama_id, episode_id, name, type, description, prompt, image_url, local_path, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      eid,
      b.drama_id != null ? b.drama_id : 1,
      b.episode_id ?? null,
      b.name || '道具',
      b.type ?? null,
      b.description ?? null,
      b.prompt ?? null,
      b.image_url || '',
      b.local_path ?? null,
      ts,
      ts
    );
    newId = eid;
  } else {
    const info = db
      .prepare(
        `INSERT INTO props (drama_id, episode_id, name, type, description, prompt, image_url, local_path, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        b.drama_id != null ? b.drama_id : 1,
        b.episode_id ?? null,
        b.name || '道具',
        b.type ?? null,
        b.description ?? null,
        b.prompt ?? null,
        b.image_url || '',
        b.local_path ?? null,
        ts,
        ts
      );
    newId = info.lastInsertRowid;
  }
  res.json({ success: true, data: { id: newId } });
});

// resume-poll 专用：可指定 status / provider_task_id / task_id
r.post('/api/v1/__seed/video_gen_pt', (req, res) => {
  const b = req.body || {};
  const eid = b.id;
  const ts = b.created_at || new Date().toISOString();
  let newId;
  if (eid != null) {
    db.prepare(
      `INSERT INTO video_generations (id, drama_id, video_url, local_path, status, provider_task_id, task_id, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      eid,
      b.drama_id ?? null,
      b.video_url || '',
      b.local_path ?? null,
      b.status ?? null,
      b.provider_task_id ?? null,
      b.task_id ?? null,
      ts,
      ts
    );
    newId = eid;
  } else {
    const info = db
      .prepare(
        `INSERT INTO video_generations (drama_id, video_url, local_path, status, provider_task_id, task_id, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        b.drama_id ?? null,
        b.video_url || '',
        b.local_path ?? null,
        b.status ?? null,
        b.provider_task_id ?? null,
        b.task_id ?? null,
        ts,
        ts
      );
    newId = info.lastInsertRowid;
  }
  res.json({ success: true, data: { id: newId } });
});

r.post('/api/v1/__seed/video_merge', (req, res) => {
  const b = req.body || {};
  const info = db
    .prepare(
      `INSERT INTO video_merges (episode_id, drama_id, title, provider, status, merged_url, task_id, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      b.episode_id ?? null,
      b.drama_id ?? null,
      b.title ?? null,
      b.provider || 'ffmpeg',
      b.status || 'pending',
      b.merged_url ?? null,
      b.task_id ?? null,
      b.created_at || new Date().toISOString()
    );
  res.json({ success: true, data: { id: info.lastInsertRowid } });
});

// 与 backend-node/src/app.js 的全局错误处理保持一致。
// multer 的 fileFilter / LIMIT_FILE_SIZE 错误会冒泡到这里；探针若不注册，
// Express 默认处理器会返回 HTML，无法与 Python 端对拍。
app.use((err, req, res, next) => {
  if (res.headersSent) return;
  const isFileTooLarge = err.code === 'LIMIT_FILE_SIZE' || (err.message && err.message.includes('File too large'));
  const status = isFileTooLarge ? 413 : 500;
  const message = isFileTooLarge ? '图片大小不能超过 16MB，请压缩后重试' : (err.message || '服务器错误');
  res.status(status).json({
    success: false,
    error: { code: isFileTooLarge ? 'FILE_TOO_LARGE' : 'INTERNAL_ERROR', message },
    timestamp: new Date().toISOString(),
  });
});

app.listen(port, () => {
  process.stdout.write(`PROBE_READY ${port}\n`);
});

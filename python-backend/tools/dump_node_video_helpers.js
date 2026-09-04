/*
 * 导出 backend-node videoClient 纯函数的输出基线，供 python-backend 契约测试比对。
 *
 * 用法（在 backend-node 目录下执行）：
 *   NODE_OPTIONS="" node ../python-backend/tools/dump_node_video_helpers.js
 *
 * 产物：backend-node/node_video_helpers.json
 *
 * 实现说明：videoClient.js 多数目标函数是**模块私有**的（未 export），且依赖相对
 * 路径的 require。因此把源码复制到 backend-node/src/services/ 下生成临时转储模块
 * （就地 require，相对解析才正确），末尾覆盖 module.exports 暴露私有函数，用完即删。
 */
const fs = require('fs');
const path = require('path');

const NODE_ROOT = path.join(__dirname, '..', '..', 'backend-node');
const SERVICES_DIR = path.join(NODE_ROOT, 'src', 'services');
const VIDEO_CLIENT_PATH = path.join(SERVICES_DIR, 'videoClient.js');
const TMP_MODULE = path.join(SERVICES_DIR, '__dump_video_helpers__.js');

const FN_NAMES = [
  'inferVideoProtocol',
  'isMinimaxH3Model',
  'resolveVideoProtocol',
  'parseConfigSettingsJson',
  'normalizeAspectRatioForApi',
  'omniDurationString',
  'isSeedance2FamilyModel',
  'normalizeVolcengineDuration',
  'normalizeVolcOmniDuration',
  'normalizeMinimaxH3Duration',
  'normalizeMinimaxH3Resolution',
  'getVolcVideoBase',
  'buildVideoUrl',
  'getAgnesApiRoot',
  'isAgnesBuiltinQueryEndpoint',
  'buildAgnesPollUrl',
  'buildQueryUrl',
  'getMinimaxApiRoot',
  'buildMinimaxH3PollUrl',
  'normalizeVolcModel',
  'getModelFromConfig',
  'isPlausibleHttpVideoUrl',
  'coerceHttpVideoUrl',
  'extractPollTaskStatus',
  'isPollTaskFailed',
  'videoUrlFromRecord',
  'videoUrlFromArkVideoNode',
  'pickVideoUrlFromItemList',
  'pickVideoUrlFromResultShape',
  'pickProxyVideoUrl',
  'extractAgnesVideoUrl',
  'extractMinimaxH3VideoUrl',
  'buildAgnesVideoImagePayload',
];

let F;
try {
  const src = fs.readFileSync(VIDEO_CLIENT_PATH, 'utf8');
  const guard = FN_NAMES.map(
    (n) => `  get ${n}() { return typeof ${n} === 'function' ? ${n} : null; },`
  ).join('\n');
  fs.writeFileSync(
    TMP_MODULE,
    `${src}\n\n// 追加导出（覆盖文件末尾的 module.exports 以暴露私有函数）\nmodule.exports = {\n${guard}\n};\n`,
    'utf8'
  );
  F = require(TMP_MODULE);
} finally {
  try {
    fs.unlinkSync(TMP_MODULE);
  } catch (_) {
    /* ignore */
  }
}

const missing = FN_NAMES.filter((n) => typeof F[n] !== 'function');
if (missing.length) {
  console.error('以下函数在 Node 源中未找到：', missing.join(', '));
  process.exit(1);
}

// ---------------- 输入矩阵 ----------------

const PROVIDERS = [
  'dashscope', 'gemini', 'google', 'volces', 'volcengine', 'volc', 'vidu',
  'ffir', 'kling', 'klingai', 'jimeng_ai_api', 'xai', 'grok', 'agnes',
  'minimax_h3', 'openai', '', null, 'SORA', 'VolcEngine',
];

const MODEL_NAMES = [
  'minimax-h3', 'minimax_h3', 'MiniMax-H3', 'minimax-h3-turbo', 'minimax',
  'hailuo-02', '', null, 'MINIMAX_H3',
];

// resolveVideoProtocol 的配置组合
const PROTO_CFG_CASES = [
  [{ provider: 'openai', base_url: 'https://api.x.ai/v1', model: ['grok-imagine-video'] }, null],
  [{ provider: 'openai', base_url: 'https://api.openai.com', model: ['grok-imagine-video'] }, null],
  [{ provider: 'openai', base_url: 'https://apihub.agnes-ai.com/v1', model: ['v'] }, null],
  [{ provider: 'agnes', base_url: 'https://x.com', model: ['v'] }, null],
  [{ provider: 'minimax_h3', base_url: 'https://x.com', model: ['v'] }, null],
  [{ provider: 'openai', base_url: 'https://x.com', model: ['minimax-h3'] }, null],
  [{ provider: 'openai', base_url: 'https://x.com', model: ['v'] }, 'minimax-h3'],
  [{ provider: 'kling', api_protocol: 'kling_omni', base_url: 'https://x.com', model: ['v'] }, null],
  [{ provider: 'volcengine', base_url: 'https://ark.cn-beijing.volces.com/api/v3', model: ['v'] }, null],
  [{ provider: '', base_url: '', model: [] }, null],
];

const ASPECT_RAW = [
  null, '', '   ', '9:16', '16:9', '1:1', '4:3', '3:4', '3:2', '2:3',
  '9：16', '9x16', '9X16', '9*16', '9×16', ' 9 : 16 ', 'portrait', 'landscape',
  'square', 'vertical', 'horizontal', 'PORTRAIT', '21:9', '4:5', 'garbage',
];

const DURATION_NUMS = [null, undefined, '', 0, -3, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 100, '5', '7.6', 'abc'];

const VIDEO_MODELS = [
  'doubao-seedance-1.0-pro', 'doubao-seedance-1.0-pro-fast', 'doubao-seedance-1.5-pro',
  'doubao-seedance-1-5-pro-251215', 'doubao-seedance-2.0-pro', 'doubao-seedance-2-0-pro-260128',
  'seedance2', 'seedance-2', 'mingiz-sd2', 'foo_sd2', 'sd2-bar', 'doubao-seedance-1.0-lite',
  'kling-v3-omni', 'kling-v3', 'kling-v1-5', '', null, 'wan2.6-video', '2-0-pro',
];

const URLS_FOR_BASE = [
  '', null, 'https://ark.cn-beijing.volces.com/api/v3',
  'https://ark.cn-beijing.volces.com/api/v3/',
  'https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks',
  'https://ark.cn-beijing.volces.com/api/v3/video/generations',
  'https://apihub.agnes-ai.com', 'https://apihub.agnes-ai.com/',
  'https://apihub.agnes-ai.com/v1', 'https://apihub.agnes-ai.com/v1/videos',
  'https://api.minimaxi.com', 'https://api.minimaxi.com/', 'https://api.minimaxi.com/v1',
  'https://api.minimaxi.com/v2', 'https://x.com/v1/videos/',
];

const AGNES_EP_CASES = [
  '', null, '   ', '/v1/videos/{taskId}', 'videos/{task_id}', '/v1/videos/{id}/',
  '/videos/{videoId}', '/videos/{video_id}/', '/agnesapi', 'agnesapi?x=1',
  '/custom/query/{taskId}', 'custom/{id}',
];

const POLL_IDS = ['', null, 'abc-123', 'a b/c?d=e', '任务 001'];

const URL_STRINGS = [
  null, undefined, '', '  ', 'https://cdn.x.com/a.mp4', 'http://x.com/a.mp4',
  'ftp://x.com/a.mp4', '//x.com/a.mp4', 'HTTPS://X.COM/A.MP4', '  https://x.com/a.mp4  ',
  123, { a: 1 }, 'not a url',
];

const STATUS_CASES = [
  null, undefined, '', '  ', 'succeeded', 'SUCCESS', 'failed', 'FAILURE', 'error',
  'cancelled', 'canceled', 'fail', 'processing', 'queued', 'pending',
];

// 响应解析用例
const RESPONSE_CASES = [
  null, undefined, {}, { video_url: 'https://x.com/a.mp4' }, { result_url: 'https://x.com/b.mp4' },
  { url: 'https://x.com/c.mp4' }, { output_url: 'https://x.com/d.mp4' },
  { remixed_from_video_id: 'https://x.com/e.mp4' },
  { video_url: 'not-a-url', result_url: 'https://x.com/f.mp4' },
  { metadata: { url: 'https://x.com/g.mp4' } },
  { data: { video_url: 'https://x.com/h.mp4' } },
  { data: { url: 'https://x.com/i.mp4' } },
  { video: { url: 'https://x.com/j.mp4' } },
  { video: { transcoded_video: { origin: { video_url: 'https://x.com/k.mp4' } } } },
  { item_list: [{ video_url: 'https://x.com/l.mp4' }] },
  { item_list: [{ common_attr: { transcoded_video: { origin: { video_url: 'https://x.com/m.mp4' } } } }] },
  { data: { item_list: [{ video_url: 'https://x.com/n.mp4' }] } },
  { data: { metadata: { url: 'https://x.com/o.mp4' } } },
  { result: { video_url: 'https://x.com/p.mp4' } },
  { result: { content: { video_url: 'https://x.com/q.mp4' } } },
  { content: { video_url: 'https://x.com/r.mp4' } },
  { videos: [{ video_url: 'https://x.com/s.mp4' }] },
  { generations: [{ url: 'https://x.com/t.mp4' }] },
  { works: [{ resource: { resource: 'https://x.com/u.mp4' } }] },
  { data: [{ video_url: 'https://x.com/v.mp4' }] },
  { status: 'failed', data: { status: 'FAILURE' } },
  { output: { task_status: 'SUCCEEDED' } },
  { task: { content: { url: 'https://x.com/w.mp4' } } },
  { task: { video_url: 'https://x.com/x.mp4' } },
  { task: { url: 'https://x.com/y.mp4' } },
];

const SETTINGS_CASES = [
  null, undefined, {}, { settings: null }, { settings: '' },
  { settings: '{"a":1}' }, { settings: 'not json' }, { settings: { b: 2 } },
];

const MODEL_CFG_CASES = [
  [{ model: ['a', 'b'], default_model: 'b' }, null],
  [{ model: ['a', 'b'], default_model: 'b' }, 'a'],
  [{ model: ['a', 'b'] }, null],
  [{ model: 'solo' }, null],
  [{ model: [] }, null],
  [{}, null],
  [{ model: ['a'], default_model: 'zzz' }, null],
];

const PAYLOAD_CASES = [
  [true, ['a', 'b', 'c'], 'a', 'c'],
  [true, ['only'], 'only', 'only'],
  [true, [], null, null],
  [false, ['a', 'b'], 'a', 'b'],
  [false, ['a'], 'a', 'a'],
  [false, [], 'first', null],
  [false, [], null, null],
  [true, new Array(12).fill(0).map((_, i) => 'r' + i), 'r0', 'r11'],
];

const out = {
  inferVideoProtocol: PROVIDERS.map((p) => [p, F.inferVideoProtocol(p)]),
  isMinimaxH3Model: MODEL_NAMES.map((m) => [m, F.isMinimaxH3Model(m)]),
  resolveVideoProtocol: PROTO_CFG_CASES.map(([cfg, hint]) => [[cfg, hint], F.resolveVideoProtocol(cfg, hint)]),
  parseConfigSettingsJson: SETTINGS_CASES.map((c) => [c, F.parseConfigSettingsJson(c)]),
  normalizeAspectRatioForApi: ASPECT_RAW.map((a) => [a, F.normalizeAspectRatioForApi(a)]),
  omniDurationString: VIDEO_MODELS.flatMap((m) =>
    DURATION_NUMS.map((d) => [[m, d], F.omniDurationString(m, d)])
  ),
  isSeedance2FamilyModel: VIDEO_MODELS.map((m) => [m, F.isSeedance2FamilyModel(m)]),
  normalizeVolcengineDuration: VIDEO_MODELS.flatMap((m) =>
    DURATION_NUMS.map((d) => [[m, d], F.normalizeVolcengineDuration(m, d)])
  ),
  normalizeVolcOmniDuration: VIDEO_MODELS.flatMap((m) =>
    DURATION_NUMS.map((d) => [[m, d], F.normalizeVolcOmniDuration(m, d)])
  ),
  normalizeMinimaxH3Duration: DURATION_NUMS.map((d) => [d, F.normalizeMinimaxH3Duration(d)]),
  normalizeMinimaxH3Resolution: [
    null, '', '  ', '768P', '768p', '1080p', '1080', '2K', '2k', '4K', '720p', 'res-768-x',
  ].map((r) => [r, F.normalizeMinimaxH3Resolution(r)]),
  getVolcVideoBase: URLS_FOR_BASE.map((u) => [{ base_url: u }, F.getVolcVideoBase({ base_url: u })]),
  buildVideoUrl: URLS_FOR_BASE.flatMap((u) => [
    [{ base_url: u, provider: 'volcengine' }, {}, ['base', u, 'volcengine', {}]],
  ]).map(([cfg, opts]) => [cfg, F.buildVideoUrl(cfg, opts)])
    .concat(
      URLS_FOR_BASE.flatMap((u) => [
        [[{ base_url: u, provider: 'openai' }, {}], F.buildVideoUrl({ base_url: u, provider: 'openai' }, {})],
        [[{ base_url: u, provider: 'openai', endpoint: 'videos' }, {}], F.buildVideoUrl({ base_url: u, provider: 'openai', endpoint: 'videos' }, {})],
        [[{ base_url: u, provider: 'openai' }, { defaultEndpoint: '/v1/videos/generations' }], F.buildVideoUrl({ base_url: u, provider: 'openai' }, { defaultEndpoint: '/v1/videos/generations' })],
      ])
    ),
  getAgnesApiRoot: URLS_FOR_BASE.map((u) => [u, F.getAgnesApiRoot(u)]),
  isAgnesBuiltinQueryEndpoint: AGNES_EP_CASES.map((ep) => [ep, F.isAgnesBuiltinQueryEndpoint(ep)]),
  buildAgnesPollUrl: URLS_FOR_BASE.flatMap((u) =>
    AGNES_EP_CASES.flatMap((ep) =>
      POLL_IDS.slice(0, 3).map((id) => [
        [{ base_url: u, query_endpoint: ep }, id],
        F.buildAgnesPollUrl({ base_url: u, query_endpoint: ep }, id),
      ])
    )
  ),
  buildQueryUrl: URLS_FOR_BASE.flatMap((u) =>
    [
      { base_url: u, provider: 'volcengine' },
      { base_url: u, provider: 'agnes' },
      { base_url: u, provider: 'minimax_h3' },
      { base_url: u, provider: 'dashscope' },
      { base_url: u, provider: 'openai', api_protocol: 'sora' },
      { base_url: u, provider: 'openai', api_protocol: 'xai' },
      { base_url: u, provider: 'openai', api_protocol: 'veo3' },
      { base_url: u, provider: 'openai', api_protocol: 'volcengine_omni' },
      { base_url: u, provider: 'openai' },
      { base_url: u, provider: 'openai', query_endpoint: 'q/{taskId}' },
    ].flatMap((cfg) =>
      POLL_IDS.slice(0, 3).map((id) => [[cfg, id], F.buildQueryUrl(cfg, id)])
    )
  ),
  getMinimaxApiRoot: URLS_FOR_BASE.map((u) => [u, F.getMinimaxApiRoot(u)]),
  buildMinimaxH3PollUrl: URLS_FOR_BASE.flatMap((u) =>
    [
      null, '/v2/query/video_generation', 'query/video_generation?task_id=1',
      '/v1/query/video_generation', '/custom/{taskId}', '/v2/query/video_generation/{task_id}',
    ].flatMap((ep) =>
      POLL_IDS.slice(0, 3).map((id) => [
        [{ base_url: u, query_endpoint: ep }, id],
        F.buildMinimaxH3PollUrl({ base_url: u, query_endpoint: ep }, id),
      ])
    )
  ),
  normalizeVolcModel: [
    null, '', 'doubao-seedance-1.0-pro', 'DOUBAO-SEEDANCE-1.0-PRO',
    'doubao-seedance-1-0-pro-250528', 'doubao-seedance-2.0-pro',
    'doubao-seedance-1.0-lite', 'kling-v1-5', 'unknown-model',
  ].map((n) => [n, F.normalizeVolcModel(n)]),
  getModelFromConfig: MODEL_CFG_CASES.map(([cfg, pm]) => [[cfg, pm], F.getModelFromConfig(cfg, pm)]),
  isPlausibleHttpVideoUrl: URL_STRINGS.map((s) => [s, F.isPlausibleHttpVideoUrl(s)]),
  coerceHttpVideoUrl: URL_STRINGS.map((s) => [s, F.coerceHttpVideoUrl(s)]),
  extractPollTaskStatus: RESPONSE_CASES.map((d) => [d, F.extractPollTaskStatus(d)]),
  isPollTaskFailed: STATUS_CASES.map((s) => [s, F.isPollTaskFailed(s)]),
  videoUrlFromRecord: RESPONSE_CASES.map((d) => [d, F.videoUrlFromRecord(d)]),
  videoUrlFromArkVideoNode: RESPONSE_CASES.map((d) => [d, F.videoUrlFromArkVideoNode(d)]),
  pickVideoUrlFromItemList: [
    null, [], [{}], [{ video_url: 'https://x.com/a.mp4' }],
    [{ common_attr: { transcoded_video: { origin: { video_url: 'https://x.com/b.mp4' } } } }],
    [{ video: { url: 'https://x.com/c.mp4' } }], [{ result_url: 'https://x.com/d.mp4' }],
  ].map((l) => [l, F.pickVideoUrlFromItemList(l)]),
  pickVideoUrlFromResultShape: RESPONSE_CASES.map((d) => [d, F.pickVideoUrlFromResultShape(d)]),
  pickProxyVideoUrl: RESPONSE_CASES.map((d) => [d, F.pickProxyVideoUrl(d)]),
  extractAgnesVideoUrl: RESPONSE_CASES.map((d) => [d, F.extractAgnesVideoUrl(d)]),
  extractMinimaxH3VideoUrl: RESPONSE_CASES.map((d) => [d, F.extractMinimaxH3VideoUrl(d)]),
  buildAgnesVideoImagePayload: PAYLOAD_CASES.map(([omni, refs, first, last]) => [
    { useOmniReference: omni, resolvedRefs: refs, firstResolved: first, lastResolved: last },
    F.buildAgnesVideoImagePayload({ useOmniReference: omni, resolvedRefs: refs, firstResolved: first, lastResolved: last }),
  ]),
};

const target = path.join(NODE_ROOT, 'node_video_helpers.json');
fs.writeFileSync(target, JSON.stringify(out, null, 2), 'utf8');
console.log('dumped ->', target);

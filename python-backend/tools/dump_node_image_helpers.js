/*
 * 导出 backend-node imageClient 纯函数的输出基线，供 python-backend 契约测试比对。
 *
 * 用法（在 backend-node 目录下执行）：
 *   NODE_OPTIONS="" node ../python-backend/tools/dump_node_image_helpers.js
 *
 * 产物：backend-node/node_image_helpers.json
 *
 * 实现说明：imageClient.js 的尺寸/比例/协议推断函数都是**模块私有**的（未 export），
 * 且依赖相对路径的 require('./aiConfigService')。因此把源码复制到
 * backend-node/src/services/ 下生成一个临时转储模块（就地 require，相对解析才正确），
 * 末尾追加 module.exports 覆盖原导出以暴露私有函数，用完即删。
 */
const fs = require('fs');
const path = require('path');

const NODE_ROOT = path.join(__dirname, '..', '..', 'backend-node');
const SERVICES_DIR = path.join(NODE_ROOT, 'src', 'services');
const IMG_CLIENT_PATH = path.join(SERVICES_DIR, 'imageClient.js');
const TMP_MODULE = path.join(SERVICES_DIR, '__dump_image_helpers__.js');

const FN_NAMES = [
  'mergeNegativePromptFragments',
  'inferProtocol',
  'fixSeedreamSize',
  'fixAgnesImageSize',
  'dashScopeSize',
  'geminiAspectRatio',
  'buildGeminiImageConfig',
  'nanoBananaAspectRatio',
  'klingImageAspectRatio',
  'closestGeminiAspectRatioFromPixels',
];

let F;
try {
  const src = fs.readFileSync(IMG_CLIENT_PATH, 'utf8');
  const guard = FN_NAMES.map(
    (n) => `  get ${n}() { return typeof ${n} === 'function' ? ${n} : null; },`
  ).join('\n');
  fs.writeFileSync(TMP_MODULE, `${src}\n\n// 追加导出（覆盖文件末尾的 module.exports 以暴露私有函数）\nmodule.exports = {\n${guard}\n};\n`, 'utf8');
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

const SIZES = [
  null,
  '',
  'garbage',
  '1024x1024',
  '1024*1024',
  '1440x2560',
  '2560x1440',
  '1920x1080',
  '1080x1920',
  '1280x1280',
  '2048x2048',
  '768x768',
  '512x512',
  '16:9',
  '9:16',
  '1:1',
  '4:3',
  '3:4',
  '21:9',
  '3:2',
  '2:3',
  '5:4',
  '4:5',
];

const PROTO_CASES = [
  ['dashscope', 'wan2.6-image'],
  ['qwen_image', 'qwen-image-max'],
  ['nano_banana', 'nano-banana'],
  ['gemini', 'gemini-2.5-flash-image'],
  ['google', 'gemini-3-pro-image'],
  ['volcengine', 'doubao-seedream-4-5'],
  ['volc', 'x'],
  ['volces', 'x'],
  ['kling', 'kling-v1-5'],
  ['klingai', 'x'],
  ['', 'kling-v2'],
  ['', 'doubao-seedream-3'],
  ['agnes', 'agnes-image-2'],
  ['', 'agnes-image-2.0'],
  ['', 'apihub.agnes-ai.com/foo'],
  ['openai', 'dall-e-3'],
  ['', 'gpt-image-1'],
];

const MODELS_FOR_GEMINI_CFG = [
  'gemini-2.5-flash-image',
  'gemini-3-pro-image',
  'gemini-3.1-flash-image',
  'gemini-2.5-pro',
];

const NEG_CASES = [
  ['', ''],
  ['auto-neg', ''],
  ['', 'user-neg'],
  ['auto-neg', 'user-neg'],
  ['  spaced  ', '  b  '],
];

const out = {
  fixSeedreamSize: SIZES.map((s) => [s, F.fixSeedreamSize(s)]),
  fixAgnesImageSize: SIZES.map((s) => [s, F.fixAgnesImageSize(s)]),
  dashScopeSize: SIZES.map((s) => [s, F.dashScopeSize(s)]),
  geminiAspectRatio: SIZES.map((s) => [s, F.geminiAspectRatio(s)]),
  nanoBananaAspectRatio: SIZES.map((s) => [s, F.nanoBananaAspectRatio(s)]),
  klingImageAspectRatio: SIZES.map((s) => [s, F.klingImageAspectRatio(s)]),
  inferProtocol: PROTO_CASES.map(([p, m]) => [[p, m], F.inferProtocol(p, m)]),
  mergeNegativePromptFragments: NEG_CASES.map(([a, b]) => [[a, b], F.mergeNegativePromptFragments(a, b)]),
  buildGeminiImageConfig: MODELS_FOR_GEMINI_CFG.flatMap((m) =>
    SIZES.map((s) => [[m, s], F.buildGeminiImageConfig(F.geminiAspectRatio(s), m, s)])
  ),
  closestGeminiAspectRatioFromPixels: [
    [100, 100], [1440, 2560], [2560, 1440], [1920, 1080], [1080, 1920],
    [768, 1024], [1024, 768], [0, 100], [100, 0], [1000, 1333],
  ].map(([w, h]) => [[w, h], F.closestGeminiAspectRatioFromPixels(w, h)]),
};

const target = path.join(NODE_ROOT, 'node_image_helpers.json');
fs.writeFileSync(target, JSON.stringify(out, null, 2), 'utf8');
console.log('dumped ->', target);

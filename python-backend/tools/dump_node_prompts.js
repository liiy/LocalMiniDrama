/*
 * 导出 backend-node aiClient.EXTRACT_PROMPTS 的提示词基线，供 python-backend 契约测试比对。
 *
 * 用法（在 backend-node 目录下执行）：
 *   node ../python-backend/tools/dump_node_prompts.js
 *
 * 产物：backend-node/node_prompts.json
 * 注意：若环境注入了 IDE 的 NODE_OPTIONS preload，需先清空，否则 require 会失败：
 *   NODE_OPTIONS="" node tools/dump_node_prompts.js
 */
const fs = require('fs');
const path = require('path');

const aiClient = require(path.join(__dirname, '..', '..', 'backend-node', 'src', 'services', 'aiClient'));

const out = {};
for (const k of ['character', 'scene', 'prop']) {
  const p = aiClient.EXTRACT_PROMPTS[k];
  out[k] = {
    system: p.system,
    user: p.user('X'),
    userNoName: p.user(''),
  };
}

const target = path.join(__dirname, '..', '..', 'backend-node', 'node_prompts.json');
fs.writeFileSync(target, JSON.stringify(out), null, 2), 'utf8';
console.log('dumped ->', target);

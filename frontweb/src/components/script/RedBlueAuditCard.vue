<template>
  <div v-if="auditReport && (auditReport.blue_checks?.length || auditReport.red_complaints?.length || auditReport.verdict)" class="red-blue-audit-card">
    <div class="audit-header">
      <div class="header-left">
        <span class="audit-icon">⚖️</span>
        <span class="audit-title">红蓝对抗质检自审 · 阶段 {{ stageNumber }}</span>
        <el-tag :type="verdictTagType" size="small" effect="dark" class="verdict-tag">
          {{ verdictLabel }}
        </el-tag>
      </div>
      <div class="header-right">
        <span v-if="auditReport.confidence_score" class="confidence-text">
          置信度: {{ Math.round(auditReport.confidence_score * 100) }}%
        </span>
        <el-button link size="small" @click="collapsed = !collapsed">
          {{ collapsed ? '展开' : '收起' }}
        </el-button>
      </div>
    </div>

    <div v-show="!collapsed" class="audit-body">
      <!-- 蓝军客观合规审查 -->
      <div class="audit-track blue-track">
        <div class="track-title">
          <span class="track-dot blue"></span>
          <span>🔵 蓝军客观合规基准</span>
          <el-tag size="small" type="success" effect="plain">{{ auditReport.blue_checks?.length || 0 }} 项</el-tag>
        </div>
        <ul class="track-list">
          <li v-for="(check, idx) in auditReport.blue_checks || []" :key="'blue_' + idx" class="check-item passed">
            <span class="icon-status">✓</span>
            <span class="text-content">{{ check }}</span>
          </li>
          <li v-if="!auditReport.blue_checks?.length" class="empty-tip">暂无蓝军审查项</li>
        </ul>
      </div>

      <!-- 红军魔鬼挑刺阻断 -->
      <div class="audit-track red-track">
        <div class="track-title">
          <span class="track-dot red"></span>
          <span>🔴 红军魔鬼挑刺批判</span>
          <el-tag size="small" :type="auditReport.red_complaints?.length ? 'danger' : 'info'" effect="plain">
            {{ auditReport.red_complaints?.length || 0 }} 处建议
          </el-tag>
        </div>
        <ul class="track-list">
          <li v-for="(complaint, idx) in auditReport.red_complaints || []" :key="'red_' + idx" class="check-item complaint">
            <span class="icon-status">⚠️</span>
            <span class="text-content">{{ complaint }}</span>
          </li>
          <li v-if="!auditReport.red_complaints?.length" class="empty-tip success">
            🎉 零硬伤！未检出任何剧情漏洞或格式冲突。
          </li>
        </ul>
      </div>

      <!-- 底部动作条 -->
      <div class="audit-actions" v-if="showActions && auditReport.red_complaints?.length">
        <el-button size="small" type="warning" plain @click="$emit('accept-feedback', auditReport)">
          ⚡ 采纳红军建议并自愈修补
        </el-button>
        <el-button size="small" type="info" plain @click="$emit('ignore-and-pass', auditReport)">
          放行通过
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  stageNumber: {
    type: Number,
    default: 1
  },
  auditReport: {
    type: Object,
    default: () => ({
      verdict: 'BLUE_PASS',
      blue_checks: [],
      red_complaints: [],
      confidence_score: 0.95
    })
  },
  showActions: {
    type: Boolean,
    default: true
  }
})

defineEmits(['accept-feedback', 'ignore-and-pass'])

const collapsed = ref(false)

const verdictLabel = computed(() => {
  const v = props.auditReport?.verdict
  if (v === 'BLUE_PASS' || v === 'pass') return '🔵 蓝军放行'
  if (v === 'YELLOW_WARN' || v === 'warn') return '🟡 黄色警告 (自动吸纳建议)'
  if (v === 'RED_BLOCKING' || v === 'blocking') return '🔴 红军阻断 (触发自愈重构)'
  return '质检完成'
})

const verdictTagType = computed(() => {
  const v = props.auditReport?.verdict
  if (v === 'BLUE_PASS' || v === 'pass') return 'success'
  if (v === 'YELLOW_WARN' || v === 'warn') return 'warning'
  if (v === 'RED_BLOCKING' || v === 'blocking') return 'danger'
  return 'info'
})
</script>

<style scoped>
.red-blue-audit-card {
  margin: 12px 0;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color-overlay);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
  overflow: hidden;
  transition: all 0.3s ease;
}

.audit-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: rgba(64, 158, 255, 0.05);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.audit-icon {
  font-size: 16px;
}

.audit-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.verdict-tag {
  font-weight: 600;
}

.confidence-text {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-right: 8px;
}

.audit-body {
  padding: 14px 16px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 768px) {
  .audit-body {
    grid-template-columns: 1fr;
  }
}

.audit-track {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.blue-track {
  border-left: 3px solid #409eff;
}

.red-track {
  border-left: 3px solid #f56c6c;
}

.track-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.track-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 180px;
  overflow-y: auto;
}

.check-item {
  font-size: 12px;
  line-height: 1.5;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 4px;
}

.check-item.passed {
  color: var(--el-color-success);
  background: rgba(103, 194, 58, 0.08);
}

.check-item.complaint {
  color: var(--el-color-danger);
  background: rgba(245, 108, 108, 0.08);
}

.empty-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  padding: 6px 0;
}

.empty-tip.success {
  color: var(--el-color-success);
}

.audit-actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
}
</style>

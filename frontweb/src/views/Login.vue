<template>
  <div class="login-container">
    <!-- 背景光晕装饰 -->
    <div class="bg-glow glow-1"></div>
    <div class="bg-glow glow-2"></div>

    <!-- 顶部主题切换 -->
    <div class="top-bar">
      <el-button class="btn-theme" text @click="toggle">
        <el-icon><Sunny v-if="isDark" /><Moon v-else /></el-icon>
        {{ isDark ? '浅色模式' : '暗色模式' }}
      </el-button>
    </div>

    <!-- 登录卡片 -->
    <div class="login-card">
      <div class="login-header">
        <div class="logo-icon">
          <el-icon :size="36"><Lock /></el-icon>
        </div>
        <h1 class="logo-title">本地短剧助手</h1>
        <p class="logo-subtitle">LocalMiniDrama 安全访问授权</p>
      </div>

      <el-alert
        v-if="statusChecked && !authEnabled"
        title="服务端当前未开启安全鉴权"
        type="info"
        description="系统当前处于开发开放模式，可直接点击下方按钮快速进入。"
        show-icon
        :closable="false"
        class="mb-4"
      />

      <el-form ref="formRef" :model="form" :rules="rules" class="login-form" @submit.prevent="handleLogin">
        <el-form-item v-if="authEnabled" prop="token">
          <el-input
            v-model="form.token"
            type="password"
            size="large"
            placeholder="请输入 API Token (访问密钥)"
            show-password
            :prefix-icon="Key"
            @keyup.enter="handleLogin"
          />
        </el-form-item>

        <div v-if="authEnabled" class="form-options">
          <el-checkbox v-model="rememberMe">记住访问密钥 (下次自动登录)</el-checkbox>
        </div>

        <el-button
          type="primary"
          size="large"
          class="submit-btn"
          :loading="loading"
          @click="handleLogin"
        >
          {{ authEnabled ? '验证并进入系统' : '直接进入系统' }}
        </el-button>
      </el-form>

      <!-- 提示信息折叠说明 -->
      <div class="config-guide">
        <el-collapse>
          <el-collapse-item title="如何获取或配置安全访问 Token？" name="1">
            <div class="guide-content">
              <p>可在后端以下任一位置设置 API Token：</p>
              <ol>
                <li>
                  <strong>配置文件：</strong>
                  <code>python-backend/configs/config.yaml</code>
                  <pre><code>security:
  auth_enabled: true
  api_token: "your-custom-secure-token"</code></pre>
                </li>
                <li>
                  <strong>环境变量 / .env 文件：</strong>
                  <pre><code>LMD_AUTH_ENABLED=true
LMD_API_TOKEN=your-custom-secure-token</code></pre>
                </li>
              </ol>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, Key, Sunny, Moon } from '@element-plus/icons-vue'
import { useTheme } from '@/composables/useTheme'
import { authAPI } from '@/api/auth'

const TOKEN_KEY = 'lmd_api_token'

const router = useRouter()
const route = useRoute()
const { isDark, toggle } = useTheme()

const formRef = ref(null)
const loading = ref(false)
const statusChecked = ref(false)
const authEnabled = ref(true)
const rememberMe = ref(true)

const form = reactive({
  token: localStorage.getItem(TOKEN_KEY) || ''
})

const rules = {
  token: [
    { required: true, message: '请输入系统 API Token', trigger: 'blur' },
    { min: 1, message: 'Token 不能为空', trigger: 'blur' }
  ]
}

onMounted(async () => {
  try {
    const res = await authAPI.getStatus()
    authEnabled.value = !!res?.auth_enabled
    statusChecked.value = true

    // 如果服务端未开启鉴权，或携带有效 token 且已验证，可直接跳转
    if (!res?.auth_enabled) {
      // 未开鉴权，如果不是主动退出跳转过来的，允许自动进入
      if (!route.query.logged_out) {
        // 也可以让用户看一眼或者直接进
      }
    } else if (res?.authenticated) {
      // 已经有有效 token
      const redirect = route.query.redirect || '/'
      router.replace(redirect)
    }
  } catch (e) {
    statusChecked.value = true
  }
})

async function handleLogin() {
  if (!authEnabled.value) {
    const redirect = route.query.redirect || '/'
    router.replace(redirect)
    return
  }

  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      const res = await authAPI.login(form.token.trim())
      const token = res?.token || form.token.trim()
      
      if (rememberMe.value) {
        localStorage.setItem(TOKEN_KEY, token)
      } else {
        sessionStorage.setItem(TOKEN_KEY, token)
      }

      ElMessage.success('身份验证成功')
      const redirect = route.query.redirect || '/'
      router.replace(redirect)
    } catch (e) {
      // 错误信息已在 axios 拦截器中提示
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-container {
  position: relative;
  min-height: 100vh;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bg-page);
  overflow: hidden;
  padding: 24px;
}

.top-bar {
  position: absolute;
  top: 20px;
  right: 24px;
  z-index: 10;
}

.bg-glow {
  position: absolute;
  width: 450px;
  height: 450px;
  border-radius: 50%;
  filter: blur(120px);
  pointer-events: none;
  opacity: 0.15;
}

.glow-1 {
  background: #6366f1;
  top: 10%;
  left: 20%;
}

.glow-2 {
  background: #ec4899;
  bottom: 15%;
  right: 20%;
}

.login-card {
  position: relative;
  z-index: 2;
  width: 100%;
  max-width: 440px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 40px 32px;
  box-shadow: var(--shadow);
}

.login-header {
  text-align: center;
  margin-bottom: 28px;
}

.logo-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: 16px;
  background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
  color: #fff;
  margin-bottom: 16px;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
}

.logo-title {
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 6px 0;
  color: var(--text-bright);
}

.logo-subtitle {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
}

.login-form {
  margin-top: 24px;
}

.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  font-size: 13px;
}

.submit-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border: none;
}

.submit-btn:hover {
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
}

.config-guide {
  margin-top: 28px;
  border-top: 1px dashed var(--border-color);
  padding-top: 16px;
}

:deep(.el-collapse) {
  border: none;
}

:deep(.el-collapse-item__header) {
  font-size: 12px;
  color: var(--text-subtle);
  background: transparent;
  border: none;
}

:deep(.el-collapse-item__wrap) {
  background: transparent;
  border: none;
}

.guide-content {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
}

.guide-content code {
  background: var(--bg-inner);
  padding: 2px 6px;
  border-radius: 4px;
  color: #6366f1;
}

.guide-content pre {
  background: var(--bg-inner);
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 6px 0;
  border: 1px solid var(--border-color);
}

.guide-content pre code {
  background: transparent;
  padding: 0;
  color: inherit;
}
</style>

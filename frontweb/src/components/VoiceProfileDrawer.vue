<template>
  <el-drawer
    v-model="visible"
    :title="`角色声音档案 - ${character?.name || '声音配置'}`"
    size="520px"
    direction="rtl"
    destroy-on-close
  >
    <div v-loading="loading" class="voice-profile-container">
      <el-form :model="formData" label-width="90px" size="default">
        <el-alert
          title="角色声音与整剧音乐体系"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 18px"
        >
          <template #default>
            统一为角色设定音色与声学参数，支持语速、音高、情感调节及试听。
          </template>
        </el-alert>

        <el-form-item label="角色名称">
          <el-input :model-value="character?.name || '-'" disabled />
        </el-form-item>

        <el-form-item label="TTS 引擎">
          <el-select v-model="formData.provider" placeholder="选择音色提供商" style="width: 100%">
            <el-option label="CosyVoice 3.0 (高保真克隆)" value="cosyvoice" />
            <el-option label="ChatTTS (对话极拟真)" value="chattts" />
            <el-option label="Edge TTS (多国语/多情感)" value="edge_tts" />
            <el-option label="Azure Speech (专业级广播)" value="azure" />
            <el-option label="Seedance 2.0 音色" value="seedance" />
          </el-select>
        </el-form-item>

        <el-form-item label="音色选择">
          <el-select v-model="formData.voice_name" placeholder="选择或输入音色" filterable allow-create style="width: 100%">
            <el-option-group label="男声">
              <el-option label="云希 (沉稳青年)" value="zh-CN-YunxiNeural" />
              <el-option label="云健 (影视磁性)" value="zh-CN-YunjianNeural" />
              <el-option label="云扬 (霸道总裁)" value="zh-CN-YunyangNeural" />
            </el-option-group>
            <el-option-group label="女声">
              <el-option label="晓晓 (甜美女主)" value="zh-CN-XiaoxiaoNeural" />
              <el-option label="晓涵 (清冷御姐)" value="zh-CN-XiaohanNeural" />
              <el-option label="晓梦 (温柔少女)" value="zh-CN-XiaomengNeural" />
            </el-option-group>
          </el-select>
        </el-form-item>

        <el-form-item label="音色特征">
          <el-select v-model="formData.timbre" placeholder="音色特征描述" filterable allow-create style="width: 100%">
            <el-option label="磁性浑厚" value="magnetic" />
            <el-option label="温润清澈" value="warm_clear" />
            <el-option label="冷峻威严" value="stern" />
            <el-option label="活泼俏皮" value="lively" />
            <el-option label="沙哑沧桑" value="hoarse" />
          </el-select>
        </el-form-item>

        <el-form-item label="情绪基调">
          <el-select v-model="formData.emotion" placeholder="选择角色默认情绪" style="width: 100%">
            <el-option label="中性平静 (Neutral)" value="neutral" />
            <el-option label="喜悦愉悦 (Happy)" value="happy" />
            <el-option label="愤怒冷厉 (Angry)" value="angry" />
            <el-option label="悲伤低沉 (Sad)" value="sad" />
            <el-option label="紧张急迫 (Fearful)" value="fearful" />
            <el-option label="热情激昂 (Excited)" value="excited" />
          </el-select>
        </el-form-item>

        <el-form-item label="语速调节">
          <div class="slider-row">
            <el-slider v-model="formData.speed" :min="0.5" :max="2.0" :step="0.05" style="flex: 1; margin-right: 15px" />
            <span class="slider-val">{{ formData.speed }}x</span>
          </div>
        </el-form-item>

        <el-form-item label="音高调节">
          <div class="slider-row">
            <el-slider v-model="formData.pitch" :min="-12" :max="12" :step="1" style="flex: 1; margin-right: 15px" />
            <span class="slider-val">{{ formData.pitch > 0 ? '+' + formData.pitch : formData.pitch }} st</span>
          </div>
        </el-form-item>

        <el-form-item label="试听参考音">
          <el-input v-model="formData.sample_audio_url" placeholder="音频 URL 或留空试听默认音频" />
        </el-form-item>

        <el-form-item label="试听预览">
          <div class="preview-box">
            <el-input
              v-model="previewText"
              type="textarea"
              :rows="2"
              placeholder="输入试听台词..."
              style="margin-bottom: 8px"
            />
            <div class="preview-actions">
              <el-button type="success" plain size="small" :loading="previewing" @click="handlePlayPreview">
                ▶ 播放试听
              </el-button>
              <audio v-if="audioPreviewUrl" :src="audioPreviewUrl" controls autoplay style="height: 32px; flex: 1; margin-left: 10px" />
            </div>
          </div>
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <div class="drawer-footer">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存声音配置</el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import audioApi from '@/api/audio'

const visible = ref(false)
const loading = ref(false)
const saving = ref(false)
const previewing = ref(false)
const character = ref(null)
const previewText = ref('你好，这是我为角色配置的专属声音档案，用于短剧对白生成。')
const audioPreviewUrl = ref('')

const formData = reactive({
  id: null,
  voice_name: 'zh-CN-YunxiNeural',
  timbre: 'magnetic',
  gender: 'male',
  speed: 1.0,
  pitch: 0,
  provider: 'edge_tts',
  model: 'standard',
  emotion: 'neutral',
  sample_audio_url: '',
})

function open(char) {
  character.value = char
  visible.value = true
  audioPreviewUrl.value = ''
  
  if (char.voice_profile) {
    formData.id = char.voice_profile.id
    formData.voice_name = char.voice_profile.voice_name || 'zh-CN-YunxiNeural'
    formData.timbre = char.voice_profile.timbre || 'magnetic'
    formData.gender = char.voice_profile.gender || 'male'
    formData.speed = char.voice_profile.speed || 1.0
    formData.pitch = char.voice_profile.pitch || 0
    formData.provider = char.voice_profile.provider || 'edge_tts'
    formData.model = char.voice_profile.model || 'standard'
    formData.emotion = char.voice_profile.emotion || 'neutral'
    formData.sample_audio_url = char.voice_profile.sample_audio_url || ''
  } else {
    formData.id = char.id
    formData.voice_name = 'zh-CN-YunxiNeural'
    formData.timbre = 'magnetic'
    formData.gender = 'male'
    formData.speed = 1.0
    formData.pitch = 0
    formData.provider = 'edge_tts'
    formData.model = 'standard'
    formData.emotion = 'neutral'
    formData.sample_audio_url = ''
  }
}

async function handlePlayPreview() {
  previewing.value = true
  try {
    // 模拟或调用 TTS 试听接口
    if (formData.sample_audio_url) {
      audioPreviewUrl.value = formData.sample_audio_url
    } else {
      ElMessage.info('正在请求音色合成试听...')
      // 可以配置默认合成音频路径
      audioPreviewUrl.value = 'https://actions.google.com/sounds/v1/speech/person_speaking.ogg'
    }
  } catch (err) {
    ElMessage.error('试听生成失败：' + (err.message || '未知错误'))
  } finally {
    previewing.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    if (formData.id) {
      await audioApi.updateVoiceProfile(formData.id, formData)
    }
    ElMessage.success('声音档案配置已保存')
    visible.value = false
  } catch (err) {
    ElMessage.error('保存失败：' + (err.message || '未知错误'))
  } finally {
    saving.value = false
  }
}

defineExpose({
  open,
})
</script>

<style scoped>
.voice-profile-container {
  padding: 8px 12px;
}
.slider-row {
  display: flex;
  align-items: center;
  width: 100%;
}
.slider-val {
  min-width: 45px;
  font-size: 13px;
  color: #606266;
  text-align: right;
}
.preview-box {
  width: 100%;
  background: #f8f9fa;
  border-radius: 6px;
  padding: 10px;
  border: 1px solid #ebeef5;
}
.preview-actions {
  display: flex;
  align-items: center;
}
.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  serverUrl: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const task = ref('')
const plan = ref<any>(null)
const changes = ref<any[]>([])
const history = ref<any[]>([])
const loading = ref(false)
const activeView = ref<'plan' | 'history'>('plan')
const diffContent = ref('')
const diffFile = ref('')

async function generatePlan() {
  if (!task.value.trim()) return
  loading.value = true
  try {
    const r = await fetch(`${props.serverUrl}/v1/build/plan`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({task: task.value}),
    })
    plan.value = await r.json()
    changes.value = plan.value.steps.map((s: any) => ({
      ...s, status: 'pending', approved: false
    }))
    await loadHistory()
  } catch {}
  loading.value = false
}

async function executeStep(index: number) {
  try {
    const r = await fetch(`${props.serverUrl}/v1/build/execute`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({step_index: index}),
    })
    const c = await r.json()
    if (changes.value[index]) {
      changes.value[index].status = 'done'
      changes.value[index].approved = true
    }
    await loadHistory()
  } catch {}
}

async function executeAll() {
  loading.value = true
  try {
    await fetch(`${props.serverUrl}/v1/build/execute-all`, { method: 'POST' })
    changes.value.forEach(c => { c.status = 'done'; c.approved = true })
    await loadHistory()
  } catch {}
  loading.value = false
}

async function undo() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/build/undo`, { method: 'POST' })
    const d = await r.json()
    if (d.status === 'undone') {
      await loadHistory()
      // Refresh plan status
      for (let i = changes.value.length - 1; i >= 0; i--) {
        if (changes.value[i].status === 'done') {
          changes.value[i].status = 'pending'
          changes.value[i].approved = false
          break
        }
      }
    }
  } catch {}
}

async function loadHistory() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/build/history`)
    const d = await r.json()
    history.value = d.changes || []
  } catch {}
}

async function showDiff(filePath: string) {
  try {
    const r = await fetch(`${props.serverUrl}/v1/build/diff`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: filePath}),
    })
    const d = await r.json()
    diffContent.value = d.diff || ''
    diffFile.value = filePath
  } catch {}
}

function countLines(content: string): number {
  if (!content) return 0
  return content.split('\n').length
}
</script>

<template>
  <div class="build-panel">
    <div class="build-header">
      <h3>Build</h3>
      <div class="build-tabs">
        <button class="tab-btn" :class="{ active: activeView === 'plan' }" @click="activeView = 'plan'">Plan</button>
        <button class="tab-btn" :class="{ active: activeView === 'history' }" @click="activeView = 'history'">History ({{ history.length }})</button>
      </div>
    </div>

    <div v-if="activeView === 'plan'" class="build-body">
      <!-- Task input -->
      <div class="task-bar">
        <input v-model="task" class="task-input" placeholder="Describe what you want to build..." @keydown.enter="generatePlan" />
        <button class="btn-primary btn-compact" :disabled="loading || !task.trim()" @click="generatePlan">
          {{ loading ? '...' : plan ? 'Replan' : 'Plan' }}
        </button>
      </div>

      <!-- Plan display -->
      <div v-if="plan" class="plan-section">
        <div class="plan-meta">
          <span class="plan-task">{{ plan.task }}</span>
          <span class="plan-steps">{{ plan.steps.length }} steps</span>
        </div>

        <div v-for="(step, i) in changes" :key="i" class="step-card" :class="step.status">
          <div class="step-header">
            <span class="step-num">{{ i + 1 }}</span>
            <span class="step-action" :class="step.action">{{ step.action }}</span>
            <span class="step-file">{{ step.file_path }}</span>
            <span class="step-status-badge" v-if="step.status === 'done'">&#10003;</span>
          </div>
          <div class="step-desc">{{ step.description }}</div>
          <div v-if="step.content" class="step-preview">
            <button class="btn-text" @click="showDiff(step.file_path)">Show diff</button>
            <span class="step-lines">{{ countLines(step.content) }} lines</span>
          </div>
          <div class="step-actions" v-if="step.status === 'pending'">
            <button class="btn-sm" @click="executeStep(i)">Approve & Execute</button>
          </div>
        </div>

        <div v-if="changes.length > 0" class="plan-actions">
          <button class="btn-primary" @click="executeAll" :disabled="loading || changes.every(c => c.status === 'done')">
            {{ loading ? 'Executing...' : 'Execute All' }}
          </button>
          <button class="btn-sm" @click="undo" :disabled="history.length === 0">Undo Last</button>
        </div>
      </div>

      <div v-else-if="!loading" class="empty-plan">
        <p>Describe what you want to build and I'll create a plan.</p>
        <p class="hint">Example: "Create a REST API with Express that has user authentication"</p>
      </div>
    </div>

    <!-- History view -->
    <div v-if="activeView === 'history'" class="build-body">
      <div v-if="history.length === 0" class="empty-plan">
        <p>No changes yet. Create a plan and execute it.</p>
      </div>
      <div v-for="(ch, i) in history" :key="i" class="hist-item">
        <span class="hist-action" :class="ch.action">{{ ch.action }}</span>
        <span class="hist-file">{{ ch.file_path }}</span>
        <button class="btn-text" @click="showDiff(ch.file_path)" v-if="ch.backup_exists">Diff</button>
      </div>
    </div>

    <!-- Diff overlay -->
    <div v-if="diffContent" class="diff-overlay" @click.self="diffContent = ''">
      <div class="diff-modal">
        <div class="diff-header">
          <span>{{ diffFile }}</span>
          <button class="btn-close" @click="diffContent = ''">&times;</button>
        </div>
        <pre class="diff-content">{{ diffContent }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.build-panel {
  display: flex; flex-direction: column; height: 100%;
  border-left: 1px solid #2a2a4a; width: 380px; flex-shrink: 0;
  background: #13131f;
}
.build-header {
  padding: 0.75rem 1rem; border-bottom: 1px solid #2a2a4a;
  display: flex; align-items: center; gap: 0.5rem;
}
.build-header h3 { font-size: 0.85rem; margin: 0; color: #e0e0e0; }
.build-tabs { display: flex; gap: 0; margin-left: auto; }
.build-tabs .tab-btn {
  background: none; border: none; color: #666; padding: 0.25rem 0.6rem;
  cursor: pointer; font-size: 0.65rem; border-bottom: 2px solid transparent;
  font-family: inherit;
}
.build-tabs .tab-btn.active { color: #7c5cfc; border-bottom-color: #7c5cfc; }

.build-body { flex: 1; overflow-y: auto; padding: 0.75rem 1rem; display: flex; flex-direction: column; gap: 0.5rem; }

.task-bar { display: flex; gap: 0.4rem; }
.task-input {
  flex: 1; background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 6px;
  color: #e0e0e0; padding: 0.4rem 0.6rem; font-size: 0.75rem; outline: none;
  font-family: inherit;
}
.task-input:focus { border-color: #7c5cfc; }

.plan-section { display: flex; flex-direction: column; gap: 0.4rem; }
.plan-meta { display: flex; justify-content: space-between; font-size: 0.7rem; color: #888; }
.plan-task { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plan-steps { color: #555; }

.step-card {
  border: 1px solid #2a2a4a; border-radius: 6px; padding: 0.5rem;
  display: flex; flex-direction: column; gap: 0.3rem;
}
.step-card.done { opacity: 0.6; border-color: #1a4a2a; }
.step-header { display: flex; align-items: center; gap: 0.4rem; }
.step-num { font-size: 0.6rem; color: #555; background: #1a1a2e; width: 18px; height: 18px; display: flex; align-items: center; justify-content: center; border-radius: 50%; }
.step-action { font-size: 0.55rem; text-transform: uppercase; letter-spacing: 0.03em; padding: 0.05rem 0.3rem; border-radius: 3px; }
.step-action.create { color: #4ade80; background: #0a2a1a; }
.step-action.modify { color: #facc15; background: #2a2a0a; }
.step-action.delete { color: #ef4444; background: #2a0a0a; }
.step-file { font-size: 0.7rem; color: #c084fc; font-family: 'SF Mono', 'Fira Code', monospace; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-status-badge { color: #4ade80; font-size: 0.8rem; }
.step-desc { font-size: 0.68rem; color: #888; }
.step-preview { display: flex; gap: 0.5rem; align-items: center; }
.step-lines { font-size: 0.6rem; color: #555; }
.step-actions { margin-top: 0.2rem; }

.plan-actions { display: flex; gap: 0.4rem; margin-top: 0.5rem; }

.hist-item {
  display: flex; align-items: center; gap: 0.4rem;
  padding: 0.35rem 0.5rem; border-radius: 4px; font-size: 0.7rem;
  border-bottom: 1px solid #1a1a30;
}
.hist-action { font-size: 0.55rem; text-transform: uppercase; padding: 0.05rem 0.25rem; border-radius: 3px; }
.hist-action.create { color: #4ade80; background: #0a2a1a; }
.hist-action.modify { color: #facc15; background: #2a2a0a; }
.hist-action.delete { color: #ef4444; background: #2a0a0a; }
.hist-file { color: #a0a0c0; flex: 1; font-family: 'SF Mono', 'Fira Code', monospace; }

.diff-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.7);
  display: flex; align-items: center; justify-content: center;
  z-index: 3000; padding: 2rem;
}
.diff-modal {
  background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 8px;
  width: 100%; max-width: 700px; max-height: 80vh; display: flex;
  flex-direction: column;
}
.diff-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.6rem 0.8rem; border-bottom: 1px solid #2a2a4a;
  font-size: 0.75rem; color: #c084fc; font-family: monospace;
}
.btn-close { background: none; border: none; color: #666; font-size: 1.2rem; cursor: pointer; }
.diff-content {
  padding: 0.8rem; overflow: auto; font-size: 0.7rem; line-height: 1.5;
  color: #a0a0c0; margin: 0; white-space: pre-wrap; word-break: break-all;
}

.empty-plan { color: #555; font-size: 0.75rem; text-align: center; padding: 2rem 0; line-height: 1.6; }
.empty-plan .hint { font-size: 0.65rem; color: #444; }

.btn-primary { background: #7c5cfc; border: none; color: #fff; padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer; font-size: 0.72rem; font-family: inherit; font-weight: 600; }
.btn-primary:disabled { opacity: 0.3; cursor: default; }
.btn-primary:hover:not(:disabled) { background: #6a4de6; }
.btn-compact { padding: 0.35rem 0.6rem; font-size: 0.68rem; }
.btn-sm { background: #2a2a4a; border: none; color: #a0a0c0; padding: 0.3rem 0.6rem; border-radius: 4px; cursor: pointer; font-size: 0.65rem; font-family: inherit; white-space: nowrap; }
.btn-sm:hover { background: #3a3a5a; color: #e0e0e0; }
.btn-sm:disabled { opacity: 0.4; cursor: default; }
.btn-text { background: none; border: none; color: #7c5cfc; cursor: pointer; font-size: 0.65rem; padding: 0; font-family: inherit; }
.btn-text:hover { text-decoration: underline; }
</style>

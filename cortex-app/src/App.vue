<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import ChatView from './components/ChatView.vue'

const serverUrl = ref('http://127.0.0.1:8081')
const connected = ref(false)
const checking = ref(false)
const modelLoading = ref(false)

const agentReady = ref(false)
const identityVersion = ref(0)
const kbChunks = ref(0)
const memoryFacts = ref(0)
const impExamples = ref(0)
const impSteps = ref(0)
const impReady = ref<boolean | null>(null)
const impLoss = ref(0)
const kbSources = ref<string[]>([])
const identityMsg = ref('')
const showHelp = ref(false)

const availableModels = ref<string[]>([])
const activeModel = ref('')
const mcpEnabled = ref(false)
const orchestrationEnabled = ref(false)
const computerEnabled = ref(false)
const videoEnabled = ref(false)
const availableEditors = ref<string[]>([])
const switchingModel = ref(false)

async function checkConnection() {
  checking.value = true
  try {
    const r = await fetch(`${serverUrl.value}/health`, { signal: AbortSignal.timeout(3000) })
    connected.value = r.ok
    if (r.ok) {
      const data = await r.json()
      modelLoading.value = data.model_loaded === false
      await Promise.all([fetchAgentState(), fetchImpState(), fetchKBState(), fetchCapabilities()])
    } else {
      modelLoading.value = false
    }
  } catch {
    connected.value = false
    modelLoading.value = false
  }
  checking.value = false
}

async function fetchCapabilities() {
  try {
    const r = await fetch(`${serverUrl.value}/v1/capabilities`, { signal: AbortSignal.timeout(3000) })
    if (r.ok) {
      const c = await r.json()
      availableModels.value = c.models?.available || []
      activeModel.value = c.models?.default || ''
      mcpEnabled.value = c.mcp?.enabled || false
      orchestrationEnabled.value = c.orchestration?.enabled || false
      computerEnabled.value = c.computer_control?.enabled || false
      videoEnabled.value = c.video_editing?.enabled || false
      availableEditors.value = c.video_editing?.editors || []
    }
  } catch {}
}

async function selectModel(model: string) {
  switchingModel.value = true
  try {
    await fetch(`${serverUrl.value}/v1/models/select`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model}),
      signal: AbortSignal.timeout(5000),
    })
    activeModel.value = model
  } catch {}
  switchingModel.value = false
}

async function fetchAgentState() {
  try {
    const r = await fetch(`${serverUrl.value}/v1/agent/state`, { signal: AbortSignal.timeout(3000) })
    if (r.ok) {
      const s = await r.json()
      agentReady.value = s.status === 'active'
      identityVersion.value = s.identity_version ?? 0
      kbChunks.value = s.kb_chunks ?? 0
      memoryFacts.value = s.facts_stored ?? 0
    } else {
      agentReady.value = false
    }
  } catch {
    agentReady.value = false
  }
}

async function fetchImpState() {
  try {
    const r = await fetch(`${serverUrl.value}/v1/improvement`, { signal: AbortSignal.timeout(3000) })
    if (r.ok) {
      const s = await r.json()
      if (s.status === 'disabled') {
        impReady.value = null
        impExamples.value = 0
        impSteps.value = 0
        impLoss.value = 0
        return
      }
      impReady.value = s.ready ?? false
      impExamples.value = s.examples_collected ?? 0
      impSteps.value = s.improvement_steps ?? 0
      impLoss.value = s.avg_train_loss ?? 0
    } else {
      impReady.value = null
    }
  } catch {
    impReady.value = null
  }
}

async function saveIdentity() {
  identityMsg.value = 'saving...'
  try {
    const r = await fetch(`${serverUrl.value}/v1/agent/identity/save`, { method: 'POST', signal: AbortSignal.timeout(5000) })
    identityMsg.value = r.ok ? 'saved' : 'error'
  } catch { identityMsg.value = 'error' }
  setTimeout(() => identityMsg.value = '', 2000)
}

async function resetIdentity() {
  identityMsg.value = 'resetting...'
  try {
    const r = await fetch(`${serverUrl.value}/v1/agent/identity/reset`, { method: 'POST', signal: AbortSignal.timeout(5000) })
    identityMsg.value = r.ok ? 'reset' : 'error'
    if (r.ok) await fetchAgentState()
  } catch { identityMsg.value = 'error' }
  setTimeout(() => identityMsg.value = '', 2000)
}

async function fetchKBState() {
  try {
    const r = await fetch(`${serverUrl.value}/v1/knowledge-base`, { signal: AbortSignal.timeout(3000) })
    if (r.ok) {
      const s = await r.json()
      if (s.status === 'active') {
        kbChunks.value = s.chunks ?? 0
        kbSources.value = s.sources ?? []
      }
    }
  } catch { }
}

let pollTimer: ReturnType<typeof setInterval> | null = null

function startPolling() {
  stopPolling()
  checkConnection()
  pollTimer = setInterval(checkConnection, 5000)
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(serverUrl, () => {
  connected.value = false
  agentReady.value = false
  startPolling()
})

onMounted(startPolling)
onUnmounted(stopPolling)
</script>

<template>
  <div class="app">
    <aside class="sidebar">
      <div class="logo">
        <span class="logo-icon">&#9670;</span>
        <span class="logo-text">CORTEX</span>
      </div>
      <div class="status">
        <div class="status-dot" :class="{ online: connected, offline: !connected, loading: modelLoading }"></div>
        <span class="status-text">
          {{ modelLoading ? 'Loading model...' : (connected ? 'Server connected' : 'Disconnected') }}
        </span>
        <button class="btn-link" @click="checkConnection" :disabled="checking">
          {{ checking ? '...' : 'refresh' }}
        </button>
      </div>
      <div class="agent-panel" v-if="connected">
        <div class="panel-label">AGENT</div>
        <div class="agent-row">
          <span class="row-label">Identity</span>
          <span class="row-value" :class="{ ready: agentReady }">
            {{ agentReady ? `v${identityVersion}` : '—' }}
          </span>
        </div>
        <div class="identity-actions" v-if="agentReady">
          <button class="btn-tiny" @click="saveIdentity" :disabled="!!identityMsg">Save</button>
          <button class="btn-tiny btn-tiny-danger" @click="resetIdentity" :disabled="!!identityMsg">Reset</button>
          <span class="identity-msg" v-if="identityMsg">{{ identityMsg }}</span>
        </div>
        <div class="agent-row">
          <span class="row-label">KB</span>
          <span class="row-value">{{ kbChunks > 0 ? `${kbChunks} chunks` : '—' }}</span>
        </div>
        <div class="agent-row">
          <span class="row-label">Memory</span>
          <span class="row-value">{{ memoryFacts > 0 ? `${memoryFacts} facts` : '—' }}</span>
        </div>
      </div>
      <div class="agent-panel" v-if="connected && impReady !== null">
        <div class="panel-label">SELF-IMPROVEMENT</div>
        <div class="agent-row">
          <span class="row-label">Status</span>
          <span class="row-value" :class="{ ready: impReady, idle: !impReady }">
            {{ impReady ? 'ready' : 'buffering' }}
          </span>
        </div>
        <div class="agent-row" v-if="impExamples > 0">
          <span class="row-label">Collected</span>
          <span class="row-value">{{ impExamples }} examples</span>
        </div>
        <div class="agent-row" v-if="impSteps > 0">
          <span class="row-label">Steps</span>
          <span class="row-value">{{ impSteps }}</span>
        </div>
        <div class="agent-row" v-if="impLoss > 0">
          <span class="row-label">Avg Loss</span>
          <span class="row-value">{{ impLoss.toFixed(4) }}</span>
        </div>
      </div>
      <div class="agent-panel" v-if="connected">
        <div class="panel-label">CAPABILITIES</div>
        <div class="agent-row">
          <span class="row-label">Model</span>
          <span class="row-value ready">{{ activeModel }}</span>
        </div>
        <div v-if="availableModels.length > 1" class="model-select">
          <select v-model="activeModel" @change="selectModel(activeModel)" :disabled="switchingModel" class="input">
            <option v-for="m in availableModels" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div class="agent-row"><span class="row-label">Computer</span><span class="row-value" :class="{ ready: computerEnabled }">{{ computerEnabled ? 'on' : 'off' }}</span></div>
        <div class="agent-row"><span class="row-label">MCP</span><span class="row-value" :class="{ ready: mcpEnabled }">{{ mcpEnabled ? 'on' : 'off' }}</span></div>
        <div class="agent-row"><span class="row-label">Orchestration</span><span class="row-value" :class="{ ready: orchestrationEnabled }">{{ orchestrationEnabled ? 'on' : 'off' }}</span></div>
        <div class="agent-row"><span class="row-label">Video Edit</span><span class="row-value" :class="{ ready: videoEnabled }">{{ videoEnabled ? (availableEditors.length ? availableEditors.join(', ') : 'on') : 'off' }}</span></div>
      </div>
      <div class="server-config">
        <label>Server URL</label>
        <input v-model="serverUrl" placeholder="http://127.0.0.1:8081" class="input" />
      </div>
      <div class="sidebar-footer">
        <button class="btn-link" @click="showHelp = !showHelp">Help</button>
        <span class="version">v0.1.0</span>
      </div>
    </aside>

    <!-- Help Modal -->
    <div class="help-overlay" v-if="showHelp" @click.self="showHelp = false">
      <div class="help-modal">
        <h3>About CORTEX</h3>
        <p>CORTEX is a local-first AI agent that runs entirely on your machine.
        No data leaves your computer.</p>

        <h4>Getting Started</h4>
        <ol>
          <li><strong>Start the server</strong> — Run <code>bash start.sh</code> in the terminal, or start the Python server manually: <code>python3 main.py</code></li>
          <li><strong>Wait for connection</strong> — The sidebar shows a green dot when connected</li>
          <li><strong>Type a message</strong> — Press <kbd>Cmd+Enter</kbd> to send</li>
        </ol>

        <h4>Features</h4>
        <table class="help-table">
          <tr><td><strong>Multi-Model</strong></td><td>Switch between local, Ollama, OpenAI, Gemini in the sidebar.</td></tr>
          <tr><td><strong>Computer Control</strong></td><td>Aura can see your screen, click, type, press keys, and run scripts.</td></tr>
          <tr><td><strong>MCP Connectors</strong></td><td>Connect to GitHub, Google Drive, Slack, and any MCP server.</td></tr>
          <tr><td><strong>Orchestration</strong></td><td>Decompose complex tasks and delegate to specialized sub-agents.</td></tr>
          <tr><td><strong>Video Editing</strong></td><td>Automate DaVinci Resolve, Premiere Pro, and CapCut.</td></tr>
          <tr><td><strong>Identity</strong></td><td>A learnable "self" vector that shapes responses. Save/Reset in sidebar.</td></tr>
          <tr><td><strong>KB</strong></td><td>Knowledge base from ingested prompt files.</td></tr>
          <tr><td><strong>Memory</strong></td><td>Permanent facts extracted from conversations.</td></tr>
          <tr><td><strong>Tools</strong></td><td>Calculate, search knowledge, read files, fetch web pages.</td></tr>
        </table>

        <h4>Tips</h4>
        <ul>
          <li>Toggle Agent mode in the chat header for identity + tool use</li>
          <li>Set a LoRA task to adapt the model to a specific topic</li>
          <li>Conversations are saved automatically in your browser</li>
        </ul>

        <button class="btn-primary" @click="showHelp = false">Got it</button>
      </div>
    </div>
    <main class="main">
      <ChatView :server-url="serverUrl" :connected="connected" />
    </main>
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; }

.app { display: flex; height: 100vh; }

.sidebar {
  width: 240px; background: #16162a; padding: 1rem;
  display: flex; flex-direction: column; gap: 1rem;
  border-right: 1px solid #2a2a4a;
}
.logo { display: flex; align-items: center; gap: 0.5rem; font-size: 1.25rem; font-weight: 700; }
.logo-icon { color: #7c5cfc; font-size: 1.5rem; }
.logo-text { color: #e0e0e0; letter-spacing: 0.1em; }

.status { display: flex; align-items: center; gap: 0.5rem; font-size: 0.8rem; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-dot.online { background: #4ade80; }
.status-dot.offline { background: #ef4444; }
.status-dot.loading { background: #facc15; animation: pulse 1s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.status-text { flex: 1; color: #888; }
.btn-link { background: none; border: none; color: #7c5cfc; cursor: pointer; font-size: 0.75rem; }
.btn-link:disabled { color: #555; }

.server-config { display: flex; flex-direction: column; gap: 0.3rem; }
.server-config label { font-size: 0.7rem; color: #666; text-transform: uppercase; letter-spacing: 0.05em; }
.input {
  background: #1e1e3a; border: 1px solid #2a2a4a; border-radius: 6px;
  color: #e0e0e0; padding: 0.5rem; font-size: 0.8rem; outline: none;
}
.input:focus { border-color: #7c5cfc; }

.agent-panel {
  display: flex; flex-direction: column; gap: 0.3rem;
  padding: 0.6rem; background: #12122a; border-radius: 8px;
  border: 1px solid #2a2a4a;
}
.panel-label {
  font-size: 0.65rem; color: #555; text-transform: uppercase;
  letter-spacing: 0.08em; font-weight: 600;
}
.agent-row { display: flex; justify-content: space-between; font-size: 0.75rem; }
.row-label { color: #888; }
.row-value { color: #666; font-weight: 600; }
.row-value.ready { color: #4ade80; }
.row-value.idle { color: #facc15; }
.identity-actions { display: flex; gap: 0.3rem; align-items: center; }
.btn-tiny {
  background: #2a2a4a; border: none; color: #888; padding: 0.2rem 0.5rem;
  border-radius: 4px; cursor: pointer; font-size: 0.7rem;
}
.btn-tiny:hover:not(:disabled) { background: #3a3a5a; color: #e0e0e0; }
.btn-tiny-danger:hover:not(:disabled) { background: #3a1a1a; color: #ef4444; }
.btn-tiny:disabled { opacity: 0.3; cursor: default; }
.identity-msg { font-size: 0.65rem; color: #4ade80; }
.sidebar-footer { margin-top: auto; }
.version { font-size: 0.7rem; color: #444; }
.model-select { margin-top: 0.2rem; }
.model-select select { width: 100%; font-size: 0.75rem; padding: 0.3rem 0.4rem; appearance: auto; }

.main { flex: 1; display: flex; flex-direction: column; }

.sidebar-footer { display: flex; justify-content: space-between; align-items: center; }
.sidebar-footer .btn-link { font-size: 0.7rem; }

.help-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000; padding: 1rem;
}
.help-modal {
  background: #1e1e3a; border: 1px solid #2a2a4a; border-radius: 12px;
  padding: 2rem; max-width: 520px; width: 100%; max-height: 80vh;
  overflow-y: auto; line-height: 1.6;
}
.help-modal h3 { margin: 0 0 0.5rem; color: #e0e0e0; font-size: 1.2rem; }
.help-modal h4 { margin: 1rem 0 0.4rem; color: #7c5cfc; font-size: 0.9rem; }
.help-modal p, .help-modal li { font-size: 0.85rem; color: #a0a0c0; margin: 0.3rem 0; }
.help-modal ol, .help-modal ul { padding-left: 1.2rem; }
.help-modal code { background: #2a2a4a; padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.8rem; }
.help-modal kbd { background: #2a2a4a; border: 1px solid #3a3a5a; padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.75rem; }
.help-table { width: 100%; font-size: 0.8rem; border-collapse: collapse; }
.help-table td { padding: 0.3rem 0; border-bottom: 1px solid #2a2a4a; color: #a0a0c0; vertical-align: top; }
.help-table td:first-child { width: 100px; color: #c084fc; }
.help-modal .btn-primary { margin-top: 1rem; width: 100%; }
</style>

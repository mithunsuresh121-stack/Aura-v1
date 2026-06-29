<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import ChatView from './components/ChatView.vue'
import SettingsPanel from './components/SettingsPanel.vue'

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
const showSettings = ref(false)

const availableModels = ref<string[]>([])
const activeModel = ref('')
const mcpEnabled = ref(false)
const orchestrationEnabled = ref(false)
const computerEnabled = ref(false)
const videoEnabled = ref(false)
const availableEditors = ref<string[]>([])
const switchingModel = ref(false)
const permGranted = ref(0)
const permTotal = ref(0)

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
      permGranted.value = c.permissions?.granted ?? 0
      permTotal.value = c.permissions?.total ?? 0
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
        <span class="logo-text">AURA</span>
      </div>
      <div class="status">
        <div class="status-dot" :class="{ online: connected, offline: !connected, loading: modelLoading }"></div>
        <span class="status-text">
          {{ modelLoading ? 'Loading model...' : (connected ? 'Agent ready' : 'Disconnected') }}
        </span>
        <button class="btn-link" @click="checkConnection" :disabled="checking">
          {{ checking ? '…' : '↻' }}
        </button>
      </div>

      <!-- Agent Section -->
      <div class="section" v-if="connected">
        <div class="section-title">Agent</div>
        <div class="section-items">
          <div class="item">
            <span class="item-label">Identity</span>
            <span class="item-value" :class="{ active: agentReady }">{{ agentReady ? `v${identityVersion}` : '—' }}</span>
          </div>
          <div class="item">
            <span class="item-label">KB</span>
            <span class="item-value">{{ kbChunks > 0 ? `${kbChunks}` : '—' }}</span>
          </div>
          <div class="item">
            <span class="item-label">Memory</span>
            <span class="item-value">{{ memoryFacts > 0 ? `${memoryFacts}` : '—' }}</span>
          </div>
        </div>
      </div>

      <!-- Self-Improvement -->
      <div class="section" v-if="connected && impReady !== null">
        <div class="section-title">Self-Improvement</div>
        <div class="section-items">
          <div class="item">
            <span class="item-label">Status</span>
            <span class="item-value" :class="{ active: impReady, idle: !impReady }">{{ impReady ? 'Ready' : 'Buffering' }}</span>
          </div>
          <div class="item" v-if="impExamples > 0">
            <span class="item-label">Collected</span>
            <span class="item-value">{{ impExamples }}</span>
          </div>
        </div>
      </div>

      <!-- Capabilities -->
      <div class="section" v-if="connected">
        <div class="section-title">Capabilities</div>
        <div class="caps-grid">
          <div class="caps-chip" :class="{ active: true }">
            <svg class="chip-icon" viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M2 3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3z"/></svg>
            <span class="chip-label">Model</span>
            <span class="chip-value">{{ activeModel }}</span>
          </div>
          <div class="caps-chip" :class="{ active: computerEnabled }">
            <svg class="chip-icon" viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M5.5 2a.5.5 0 0 1 .5.5V5h4V2.5a.5.5 0 0 1 1 0V5h1.5A1.5 1.5 0 0 1 14 6.5v7a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 13.5v-7A1.5 1.5 0 0 1 3.5 5H5V2.5a.5.5 0 0 1 .5-.5z"/></svg>
            <span class="chip-label">Desktop</span>
            <span class="chip-status" :class="{ on: computerEnabled }">{{ computerEnabled ? 'on' : 'off' }}</span>
          </div>
          <div class="caps-chip" :class="{ active: mcpEnabled }">
            <svg class="chip-icon" viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M0 4a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V4zm2-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1H2z"/></svg>
            <span class="chip-label">MCP</span>
            <span class="chip-status" :class="{ on: mcpEnabled }">{{ mcpEnabled ? 'on' : 'off' }}</span>
          </div>
          <div class="caps-chip" :class="{ active: orchestrationEnabled }">
            <svg class="chip-icon" viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M2 2a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V2z"/></svg>
            <span class="chip-label">Orch</span>
            <span class="chip-status" :class="{ on: orchestrationEnabled }">{{ orchestrationEnabled ? 'on' : 'off' }}</span>
          </div>
          <div class="caps-chip" :class="{ active: videoEnabled }">
            <svg class="chip-icon" viewBox="0 0 16 16" width="12" height="12"><path fill="currentColor" d="M2 3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3z"/></svg>
            <span class="chip-label">Video</span>
            <span class="chip-status" :class="{ on: videoEnabled }">{{ videoEnabled ? 'on' : 'off' }}</span>
          </div>
        </div>
      </div>

      <!-- Permissions compact -->
      <div class="section" v-if="connected && permTotal > 0">
        <div class="section-title">Permissions</div>
        <div class="perm-bar">
          <div class="perm-bar-fill" :style="{ width: (permGranted/permTotal*100) + '%' }" :class="{ full: permGranted === permTotal }"></div>
        </div>
        <div class="perm-stats">
          <span class="perm-count">{{ permGranted }}/{{ permTotal }} granted</span>
          <button class="btn-link" @click="showSettings = true">Manage</button>
        </div>
      </div>

      <div class="spacer"></div>
      <div class="server-config">
        <input v-model="serverUrl" placeholder="http://127.0.0.1:8081" class="input" />
      </div>
      <div class="sidebar-footer">
        <button class="btn-link" @click="showSettings = true">Settings</button>
        <button class="btn-link" @click="showHelp = !showHelp">Help</button>
        <span class="version">v0.1.0</span>
      </div>
    </aside>

    <SettingsPanel
      v-if="connected && showSettings"
      :server-url="serverUrl"
      :capabilities="{
        availableModels, activeModel, computerEnabled,
        mcpEnabled, orchestrationEnabled, videoEnabled, availableEditors,
      }"
      @select-model="selectModel"
      @close="showSettings = false"
    />

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
  width: 220px; background: #13131f; padding: 0.75rem;
  display: flex; flex-direction: column; gap: 0.75rem;
  border-right: 1px solid #1e1e32;
}
.logo { display: flex; align-items: center; gap: 0.4rem; font-size: 1rem; font-weight: 700; padding: 0.25rem 0; }
.logo-icon { color: #7c5cfc; font-size: 1.2rem; }
.logo-text { color: #e0e0e0; letter-spacing: 0.08em; font-size: 0.9rem; }

.status { display: flex; align-items: center; gap: 0.4rem; font-size: 0.72rem; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.status-dot.online { background: #4ade80; }
.status-dot.offline { background: #ef4444; }
.status-dot.loading { background: #facc15; animation: pulse 1s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.status-text { flex: 1; color: #888; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.btn-link { background: none; border: none; color: #7c5cfc; cursor: pointer; font-size: 0.7rem; padding: 0; font-family: inherit; }
.btn-link:disabled { color: #444; }

/* Sections */
.section { display: flex; flex-direction: column; gap: 0.25rem; }
.section-title {
  font-size: 0.6rem; color: #555; text-transform: uppercase;
  letter-spacing: 0.06em; font-weight: 600; padding: 0 0.15rem;
}
.section-items { display: flex; flex-direction: column; gap: 0.15rem; }

.item { display: flex; justify-content: space-between; align-items: center; padding: 0.2rem 0.35rem; border-radius: 4px; font-size: 0.7rem; }
.item:hover { background: #18182a; }
.item-label { color: #888; }
.item-value { color: #555; font-weight: 500; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.65rem; }
.item-value.active { color: #4ade80; }
.item-value.idle { color: #facc15; }

/* Capabilities grid */
.caps-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.25rem; }
.caps-chip {
  display: flex; align-items: center; gap: 0.25rem;
  padding: 0.3rem 0.4rem; border-radius: 6px;
  background: #0e0e1e; border: 1px solid #1a1a30; cursor: default;
}
.caps-chip.active { border-color: #2a2a4a; }
.chip-icon { color: #555; flex-shrink: 0; opacity: 0.6; }
.caps-chip.active .chip-icon { color: #7c5cfc; opacity: 1; }
.chip-label { font-size: 0.6rem; color: #666; flex: 1; white-space: nowrap; }
.caps-chip.active .chip-label { color: #a0a0c0; }
.chip-value { font-size: 0.6rem; color: #4ade80; font-family: 'SF Mono', 'Fira Code', monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 50px; }
.chip-status { font-size: 0.55rem; text-transform: uppercase; letter-spacing: 0.03em; color: #444; padding: 0.05rem 0.25rem; border-radius: 3px; background: #0e0e1e; }
.chip-status.on { color: #4ade80; background: #0a2a1a; }

/* Permission bar */
.perm-bar { height: 3px; background: #1a1a30; border-radius: 2px; overflow: hidden; }
.perm-bar-fill { height: 100%; background: #444; border-radius: 2px; transition: width 0.3s; }
.perm-bar-fill.full { background: #4ade80; }
.perm-stats { display: flex; justify-content: space-between; align-items: center; font-size: 0.65rem; }
.perm-count { color: #666; }

.spacer { flex: 1; }
.server-config { }
.input {
  background: #1a1a2e; border: 1px solid #1e1e32; border-radius: 6px;
  color: #888; padding: 0.4rem 0.5rem; font-size: 0.7rem; outline: none; width: 100%;
  font-family: inherit;
}
.input:focus { border-color: #2a2a4a; color: #e0e0e0; }

.sidebar-footer { display: flex; justify-content: flex-start; align-items: center; gap: 0.75rem; padding: 0.25rem 0; }
.sidebar-footer .btn-link { color: #555; }
.sidebar-footer .btn-link:hover { color: #7c5cfc; }
.version { font-size: 0.6rem; color: #333; margin-left: auto; }

.server-config .input { font-size: 0.6rem; color: #555; padding: 0.3rem 0.4rem; }

.main { flex: 1; display: flex; flex-direction: column; }

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

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import ChatView from './components/ChatView.vue'
import TerminalView from './components/TerminalView.vue'
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

const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0
const modKey = isMac ? 'Cmd' : 'Ctrl'

const currentView = ref<'chat' | 'terminal'>('chat')

const availableModels = ref<string[]>([])
const activeModel = ref('')
const mcpEnabled = ref(false)
const orchestrationEnabled = ref(false)
const computerEnabled = ref(false)
const videoEnabled = ref(false)
const terminalEnabled = ref(false)
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
      terminalEnabled.value = c.terminal?.enabled || false
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

      <!-- Nav -->
      <div class="nav-items">
        <button class="nav-btn" :class="{ active: currentView === 'chat' }" @click="currentView = 'chat'">
          <span class="nav-icon">&#9998;</span>
          <span>Chat</span>
        </button>
        <button class="nav-btn" :class="{ active: currentView === 'terminal' }" @click="currentView = 'terminal'">
          <span class="nav-icon">&#9551;</span>
          <span>Terminal</span>
          <span class="nav-badge" v-if="terminalEnabled">ON</span>
        </button>
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
        <div class="section-title">CAPABILITIES</div>
        <div class="caps-list">
          <div class="caps-item"><span>Model</span><span class="mono">{{ activeModel }}</span></div>
          <div class="caps-item"><span>Desktop</span><span class="badge" :class="{ on: computerEnabled }">{{ computerEnabled ? 'ON' : 'OFF' }}</span></div>
          <div class="caps-item"><span>MCP</span><span class="badge" :class="{ on: mcpEnabled }">{{ mcpEnabled ? 'ON' : 'OFF' }}</span></div>
          <div class="caps-item"><span>Orch</span><span class="badge" :class="{ on: orchestrationEnabled }">{{ orchestrationEnabled ? 'ON' : 'OFF' }}</span></div>
           <div class="caps-item"><span>Video</span><span class="badge" :class="{ on: videoEnabled }">{{ videoEnabled ? 'ON' : 'OFF' }}</span></div>
          <div class="caps-item"><span>Terminal</span><span class="badge" :class="{ on: terminalEnabled }">{{ terminalEnabled ? 'ON' : 'OFF' }}</span></div>
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
        terminalEnabled,
      }"
      @select-model="selectModel"
      @close="showSettings = false"
    />

    <!-- Help Modal -->
    <div class="help-overlay" v-if="showHelp" @click.self="showHelp = false">
      <div class="help-modal">
        <h3>About AURA</h3>
        <p>AURA is a local-first AI agent that runs entirely on your machine.
        No data leaves your computer. Available on <strong>macOS</strong>, <strong>Windows</strong>, and <strong>Linux</strong>.</p>

        <h4>Getting Started</h4>
        <ol>
          <li><strong>Start the server</strong> — Run <code>bash start.sh</code> in the terminal, or start the Python server manually: <code>python3 main.py</code></li>
          <li><strong>Wait for connection</strong> — The sidebar shows a green dot when connected</li>
          <li><strong>Type a message</strong> — Press <kbd>{{ modKey }}+Enter</kbd> to send</li>
        </ol>

        <h4>Features</h4>
        <table class="help-table">
          <tr><td><strong>Multi-Model</strong></td><td>Switch between local, Ollama, OpenAI, Gemini in the sidebar.</td></tr>
          <tr><td><strong>Computer Control</strong></td><td>Aura can see your screen, click, type, press keys, and run scripts.</td></tr>
          <tr><td><strong>MCP Connectors</strong></td><td>Connect to MCP servers for GitHub and custom tools.</td></tr>
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
      <ChatView v-if="currentView === 'chat'" :server-url="serverUrl" :connected="connected" />
      <TerminalView v-else-if="currentView === 'terminal'" :server-url="serverUrl" />
    </main>
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', sans-serif;
  background: #080812;
  color: #e8e8f0;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
::selection { background: #7c5cfc44; }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #1e1e36; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #2a2a46; }

.app { display: flex; height: 100vh; background: radial-gradient(ellipse at 20% 50%, #0a0a1e 0%, #080812 70%); }

.sidebar {
  width: 228px; background: rgba(10, 10, 20, 0.85); padding: 0.75rem;
  display: flex; flex-direction: column; gap: 0.5rem;
  border-right: 1px solid rgba(30, 30, 54, 0.6);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
}
.logo { display: flex; align-items: center; gap: 0.45rem; padding: 0.3rem 0.15rem 0.5rem; }
.logo-icon {
  width: 22px; height: 22px; border-radius: 8px;
  background: linear-gradient(135deg, #7c5cfc, #5a3cfc);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.7rem; color: #fff; font-weight: 700; flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(124, 92, 252, 0.3);
}
.logo-text { color: #e8e8f0; letter-spacing: 0.1em; font-size: 0.85rem; font-weight: 700; }

.nav-items { display: flex; flex-direction: column; gap: 0.1rem; padding: 0.25rem 0; }
.nav-btn {
  display: flex; align-items: center; gap: 0.35rem;
  background: none; border: none; color: #585870;
  padding: 0.35rem 0.5rem; border-radius: 8px;
  cursor: pointer; font-size: 0.72rem; font-family: inherit;
  text-align: left; transition: all 0.12s;
  width: 100%;
}
.nav-btn:hover { background: rgba(255,255,255,0.03); color: #8888a0; }
.nav-btn.active { background: rgba(124, 92, 252, 0.08); color: #c084fc; }
.nav-icon { font-size: 0.65rem; width: 16px; text-align: center; flex-shrink: 0; }
.nav-badge {
  font-size: 0.5rem; color: #4ade80; margin-left: auto;
  padding: 0.05rem 0.25rem; border-radius: 4px;
  background: rgba(74, 222, 128, 0.1);
}

.status { display: flex; align-items: center; gap: 0.35rem; font-size: 0.68rem; padding: 0.35rem 0.4rem; border-radius: 8px; background: rgba(255,255,255,0.02); }
.status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; position: relative; }
.status-dot.online { background: #4ade80; box-shadow: 0 0 6px rgba(74, 222, 128, 0.4); }
.status-dot.offline { background: #ef4444; }
.status-dot.loading { background: #facc15; animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
.status-text { flex: 1; color: #686880; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.btn-link { background: none; border: none; color: #7c5cfc; cursor: pointer; font-size: 0.68rem; padding: 0; font-family: inherit; transition: color 0.15s; }
.btn-link:disabled { color: #2a2a3a; }
.btn-link:hover:not(:disabled) { color: #9b7eff; }

/* Sections */
.section { display: flex; flex-direction: column; gap: 0.15rem; padding: 0.25rem 0; }
.section + .section { border-top: 1px solid rgba(30, 30, 54, 0.4); padding-top: 0.5rem; }
.section-title {
  font-size: 0.58rem; color: #484860; text-transform: uppercase;
  letter-spacing: 0.08em; font-weight: 700; padding: 0 0.35rem 0.15rem;
}
.section-items { display: flex; flex-direction: column; gap: 0.05rem; }

.item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.2rem 0.4rem; border-radius: 6px; font-size: 0.68rem;
  transition: background 0.15s;
}
.item:hover { background: rgba(255,255,255,0.03); }
.item-label { color: #686880; }
.item-value { color: #484860; font-weight: 500; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.62rem; }
.item-value.active { color: #4ade80; }
.item-value.idle { color: #facc15; }

/* Capabilities list */
.caps-list { display: flex; flex-direction: column; gap: 0.05rem; }
.caps-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.25rem 0.4rem; font-size: 0.68rem; border-radius: 6px;
  transition: background 0.15s;
}
.caps-item:hover { background: rgba(255,255,255,0.03); }
.caps-item span:first-child { color: #686880; }
.caps-item .mono { color: #4ade80; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.6rem; }
.caps-item .badge {
  font-size: 0.55rem; color: #383848; letter-spacing: 0.04em;
  padding: 0.05rem 0.3rem; border-radius: 4px; background: rgba(255,255,255,0.03);
}
.caps-item .badge.on { color: #4ade80; background: rgba(74, 222, 128, 0.1); }

/* Permission bar */
.perm-bar { height: 3px; background: rgba(255,255,255,0.04); border-radius: 2px; overflow: hidden; }
.perm-bar-fill { height: 100%; background: #484860; border-radius: 2px; transition: width 0.4s ease; }
.perm-bar-fill.full { background: linear-gradient(90deg, #4ade80, #22c55e); }
.perm-stats { display: flex; justify-content: space-between; align-items: center; font-size: 0.62rem; padding: 0 0.1rem; }
.perm-count { color: #484860; }

.spacer { flex: 1; }
.input {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(30, 30, 54, 0.6);
  border-radius: 8px; color: #686880; padding: 0.4rem 0.5rem; font-size: 0.68rem;
  outline: none; width: 100%; font-family: inherit;
  transition: border-color 0.2s, color 0.2s;
}
.input:focus { border-color: rgba(124, 92, 252, 0.4); color: #e8e8f0; }

.sidebar-footer {
  display: flex; justify-content: flex-start; align-items: center;
  gap: 0.6rem; padding: 0.3rem 0.1rem;
}
.sidebar-footer .btn-link { color: #484860; font-size: 0.62rem; }
.sidebar-footer .btn-link:hover { color: #7c5cfc; }
.version { font-size: 0.55rem; color: #2a2a3a; margin-left: auto; }

.server-config .input { font-size: 0.58rem; color: #484860; padding: 0.3rem 0.4rem; }

.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }

.help-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.7);
  backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000; padding: 1rem;
}
.help-modal {
  background: linear-gradient(135deg, #111122, #0d0d1e);
  border: 1px solid rgba(30, 30, 54, 0.6);
  border-radius: 16px; padding: 2rem; max-width: 520px; width: 100%;
  max-height: 80vh; overflow-y: auto; line-height: 1.6;
  box-shadow: 0 20px 60px rgba(0,0,0,0.4);
}
.help-modal h3 { margin: 0 0 0.5rem; color: #e8e8f0; font-size: 1.2rem; }
.help-modal h4 { margin: 1rem 0 0.4rem; color: #7c5cfc; font-size: 0.85rem; }
.help-modal p, .help-modal li { font-size: 0.82rem; color: #8888a0; margin: 0.3rem 0; }
.help-modal ol, .help-modal ul { padding-left: 1.2rem; }
.help-modal code { background: rgba(255,255,255,0.04); padding: 0.1rem 0.3rem; border-radius: 4px; font-size: 0.78rem; }
.help-modal kbd { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.72rem; }
.help-table { width: 100%; font-size: 0.78rem; border-collapse: collapse; }
.help-table td { padding: 0.3rem 0; border-bottom: 1px solid rgba(255,255,255,0.04); color: #8888a0; vertical-align: top; }
.help-table td:first-child { width: 100px; color: #c084fc; }
.help-modal .btn-primary { margin-top: 1rem; width: 100%; }
</style>

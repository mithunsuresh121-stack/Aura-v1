<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  serverUrl: string
  capabilities: {
    availableModels: string[]
    activeModel: string
    computerEnabled: boolean
    mcpEnabled: boolean
    orchestrationEnabled: boolean
    videoEnabled: boolean
    availableEditors: string[]
  }
}>()

const emit = defineEmits<{
  (e: 'selectModel', model: string): void
}>()

// Expandable sections
const expanded = ref<Record<string, boolean>>({})
const toggle = (section: string) => { expanded.value[section] = !expanded.value[section] }

// Computer control
const mousePos = ref({ x: 0, y: 0 })
const screenshotResult = ref('')
const lookResult = ref('')
const clickX = ref(500)
const clickY = ref(400)
const typeText = ref('')
const computerLoading = ref(false)
const windowName = ref('')

async function getMousePos() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/computer/mouse-position`, { method: 'POST' })
    mousePos.value = await r.json()
  } catch {}
}
async function takeScreenshot() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/computer/screenshot`, { method: 'POST' })
    const d = await r.json()
    screenshotResult.value = d.path || 'captured'
  } catch {}
}
async function look() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/computer/look`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({detail: 'brief'}),
    })
    const d = await r.json()
    lookResult.value = d.description || '(no description)'
  } catch {}
}
async function doClick() {
  try {
    await fetch(`${props.serverUrl}/v1/computer/click`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({x: clickX.value, y: clickY.value}),
    })
  } catch {}
}
async function doType() {
  if (!typeText.value) return
  try {
    await fetch(`${props.serverUrl}/v1/computer/type`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: typeText.value}),
    })
  } catch {}
}
async function getWindow() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/computer/active-window`, { method: 'POST' })
    const d = await r.json()
    windowName.value = d.window || 'unknown'
  } catch {}
}

// MCP tools
const mcpTools = ref<any[]>([])
const mcpResult = ref('')
const mcpToolName = ref('')
const mcpArgs = ref('')

async function listMcpTools() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/mcp/tools`)
    const d = await r.json()
    mcpTools.value = d.tools || []
  } catch {}
}
async function callMcpTool() {
  if (!mcpToolName.value) return
  try {
    let args = {}
    if (mcpArgs.value) { try { args = JSON.parse(mcpArgs.value) } catch {} }
    const r = await fetch(`${props.serverUrl}/v1/mcp/call`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({tool: mcpToolName.value, arguments: args}),
    })
    const d = await r.json()
    mcpResult.value = d.result || '(no result)'
  } catch {}
}

// Orchestration
const agentId = ref('')
const agentRole = ref('')
const orchTask = ref('')
const orchResult = ref('')
const subAgents = ref<any[]>([])
const orchLoading = ref(false)

async function registerAgent() {
  if (!agentId.value || !agentRole.value) return
  try {
    await fetch(`${props.serverUrl}/v1/orchestrate/register-agent`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({agent_id: agentId.value, role: agentRole.value, model_name: 'local'}),
    })
    agentId.value = ''; agentRole.value = ''
    await listSubAgents()
  } catch {}
}
async function listSubAgents() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/orchestrate/agents`)
    const d = await r.json()
    subAgents.value = d.agents || []
  } catch {}
}
async function runOrchestration() {
  if (!orchTask.value) return
  orchLoading.value = true
  try {
    const r = await fetch(`${props.serverUrl}/v1/orchestrate`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({task: orchTask.value}),
    })
    const d = await r.json()
    orchResult.value = d.result || '(no result)'
  } catch {}
  orchLoading.value = false
}

// Video editing
const editDesc = ref('')
const editOutput = ref('')
const editResult = ref<any>(null)
const editLoading = ref(false)

async function runEdit() {
  if (!editDesc.value) return
  editLoading.value = true
  try {
    const r = await fetch(`${props.serverUrl}/v1/software/edit`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({description: editDesc.value, output_path: editOutput.value}),
    })
    editResult.value = await r.json()
  } catch {}
  editLoading.value = false
}
</script>

<template>
  <div class="caps-panel">
    <!-- Model -->
    <div class="caps-section" :class="{ expanded: expanded.models }">
      <div class="caps-header" @click="toggle('models')">
        <span class="caps-icon">&#9881;</span>
        <span class="caps-title">Model</span>
        <span class="caps-badge">{{ capabilities.activeModel }}</span>
        <span class="caps-arrow">{{ expanded.models ? '&#9660;' : '&#9654;' }}</span>
      </div>
      <div class="caps-body" v-if="expanded.models">
        <select v-model="capabilities.activeModel" @change="emit('selectModel', capabilities.activeModel)" class="caps-select">
          <option v-for="m in capabilities.availableModels" :key="m" :value="m">{{ m }}</option>
        </select>
      </div>
    </div>

    <!-- Computer Control -->
    <div class="caps-section" :class="{ expanded: expanded.computer }">
      <div class="caps-header" @click="toggle('computer')">
        <span class="caps-icon">&#9000;</span>
        <span class="caps-title">Computer</span>
        <span class="caps-badge" :class="{ on: capabilities.computerEnabled }">{{ capabilities.computerEnabled ? 'active' : 'off' }}</span>
        <span class="caps-arrow">{{ expanded.computer ? '&#9660;' : '&#9654;' }}</span>
      </div>
      <div class="caps-body" v-if="expanded.computer">
        <div class="caps-row">
          <button class="caps-btn" @click="getMousePos">Mouse Pos</button>
          <span class="caps-val">x:{{ mousePos.x }} y:{{ mousePos.y }}</span>
        </div>
        <div class="caps-row">
          <button class="caps-btn" @click="getWindow">Active Window</button>
          <span class="caps-val">{{ windowName || '—' }}</span>
        </div>
        <div class="caps-row">
          <button class="caps-btn" @click="takeScreenshot">Screenshot</button>
          <span class="caps-val">{{ screenshotResult || '—' }}</span>
        </div>
        <div class="caps-row">
          <button class="caps-btn" @click="look">Look</button>
        </div>
        <div class="caps-val caps-desc" v-if="lookResult">{{ lookResult }}</div>
        <div class="caps-inline">
          <input v-model.number="clickX" class="caps-input" type="number" placeholder="x" />
          <input v-model.number="clickY" class="caps-input" type="number" placeholder="y" />
          <button class="caps-btn" @click="doClick">Click</button>
        </div>
        <div class="caps-inline">
          <input v-model="typeText" class="caps-input caps-input-wide" placeholder="Type something..." />
          <button class="caps-btn" @click="doType">Type</button>
        </div>
      </div>
    </div>

    <!-- MCP -->
    <div class="caps-section" :class="{ expanded: expanded.mcp }">
      <div class="caps-header" @click="toggle('mcp')">
        <span class="caps-icon">&#8644;</span>
        <span class="caps-title">MCP</span>
        <span class="caps-badge" :class="{ on: capabilities.mcpEnabled }">{{ capabilities.mcpEnabled ? 'active' : 'off' }}</span>
        <span class="caps-arrow">{{ expanded.mcp ? '&#9660;' : '&#9654;' }}</span>
      </div>
      <div class="caps-body" v-if="expanded.mcp">
        <button class="caps-btn caps-btn-full" @click="listMcpTools">List Tools</button>
        <div v-for="t in mcpTools" :key="t.name" class="mcp-tool-item">
          <span class="mcp-tool-name">{{ t.server }} / {{ t.name }}</span>
          <span class="mcp-tool-desc">{{ t.description }}</span>
        </div>
        <div class="caps-inline">
          <input v-model="mcpToolName" class="caps-input caps-input-wide" placeholder="mcp_server_toolname" />
        </div>
        <div class="caps-inline">
          <input v-model="mcpArgs" class="caps-input caps-input-wide" placeholder='{"key":"value"}' />
          <button class="caps-btn" @click="callMcpTool">Call</button>
        </div>
        <div class="caps-val caps-desc" v-if="mcpResult">{{ mcpResult }}</div>
      </div>
    </div>

    <!-- Orchestration -->
    <div class="caps-section" :class="{ expanded: expanded.orch }">
      <div class="caps-header" @click="toggle('orch')">
        <span class="caps-icon">&#9733;</span>
        <span class="caps-title">Orchestrator</span>
        <span class="caps-badge" :class="{ on: capabilities.orchestrationEnabled }">{{ capabilities.orchestrationEnabled ? 'active' : 'off' }}</span>
        <span class="caps-arrow">{{ expanded.orch ? '&#9660;' : '&#9654;' }}</span>
      </div>
      <div class="caps-body" v-if="expanded.orch">
        <div class="caps-label">Register Sub-Agent</div>
        <div class="caps-inline">
          <input v-model="agentId" class="caps-input" placeholder="agent id" />
          <input v-model="agentRole" class="caps-input" placeholder="role" />
          <button class="caps-btn" @click="registerAgent">Add</button>
        </div>
        <div class="caps-label">Run Task</div>
        <div class="caps-inline">
          <input v-model="orchTask" class="caps-input caps-input-wide" placeholder="Describe a complex task..." />
          <button class="caps-btn" :disabled="orchLoading" @click="runOrchestration">{{ orchLoading ? '...' : 'Go' }}</button>
        </div>
        <div class="caps-val caps-desc" v-if="orchResult">{{ orchResult.slice(0, 200) }}...</div>
        <div v-if="subAgents.length" class="caps-label">Sub-Agents: {{ subAgents.map(a => a.id).join(', ') }}</div>
      </div>
    </div>

    <!-- Video Editing -->
    <div class="caps-section" :class="{ expanded: expanded.video }">
      <div class="caps-header" @click="toggle('video')">
        <span class="caps-icon">&#9654;</span>
        <span class="caps-title">Video Edit</span>
        <span class="caps-badge" :class="{ on: capabilities.videoEnabled }">{{ capabilities.videoEnabled ? capabilities.availableEditors.join(', ') || 'active' : 'off' }}</span>
        <span class="caps-arrow">{{ expanded.video ? '&#9660;' : '&#9654;' }}</span>
      </div>
      <div class="caps-body" v-if="expanded.video">
        <textarea v-model="editDesc" class="caps-textarea" placeholder="Describe the edit you want (e.g. 'Create a 30-second travel montage from my clips')" rows="3"></textarea>
        <input v-model="editOutput" class="caps-input caps-input-wide" placeholder="Output path (e.g. ~/Desktop/output.mp4)" />
        <button class="caps-btn caps-btn-full" :disabled="editLoading" @click="runEdit">{{ editLoading ? 'Running...' : 'Execute Edit' }}</button>
        <div class="caps-val caps-desc" v-if="editResult">
          Status: {{ editResult.status }}<br/>
          Actions: {{ editResult.actions?.join(', ') || '—' }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.caps-panel { display: flex; flex-direction: column; gap: 0.2rem; }
.caps-section { border: 1px solid #2a2a4a; border-radius: 6px; overflow: hidden; }
.caps-header {
  display: flex; align-items: center; gap: 0.4rem; padding: 0.4rem 0.5rem;
  cursor: pointer; background: #12122a; user-select: none;
}
.caps-header:hover { background: #1a1a3a; }
.caps-icon { font-size: 0.7rem; width: 14px; text-align: center; }
.caps-title { font-size: 0.72rem; font-weight: 600; color: #c0c0e0; flex: 1; }
.caps-badge { font-size: 0.6rem; padding: 0.1rem 0.4rem; border-radius: 4px; background: #2a2a4a; color: #666; text-transform: uppercase; }
.caps-badge.on { background: #16553a; color: #4ade80; }
.caps-arrow { font-size: 0.55rem; color: #555; }
.caps-body { padding: 0.4rem 0.5rem; display: flex; flex-direction: column; gap: 0.3rem; background: #0e0e22; }
.caps-row { display: flex; align-items: center; gap: 0.3rem; }
.caps-inline { display: flex; gap: 0.3rem; align-items: center; }
.caps-btn {
  background: #2a2a4a; border: none; color: #a0a0c0; padding: 0.25rem 0.5rem;
  border-radius: 4px; cursor: pointer; font-size: 0.65rem; white-space: nowrap;
}
.caps-btn:hover { background: #3a3a5a; color: #e0e0e0; }
.caps-btn:disabled { opacity: 0.4; cursor: default; }
.caps-btn-full { width: 100%; }
.caps-input {
  background: #1e1e3a; border: 1px solid #2a2a4a; border-radius: 4px;
  color: #e0e0e0; padding: 0.25rem 0.4rem; font-size: 0.65rem; outline: none; flex: 1;
  min-width: 0; font-family: inherit;
}
.caps-input:focus { border-color: #7c5cfc; }
.caps-input-wide { flex: 2; }
.caps-val { font-size: 0.6rem; color: #888; }
.caps-desc { background: #12122a; padding: 0.3rem; border-radius: 4px; line-height: 1.4; word-break: break-all; max-height: 100px; overflow-y: auto; }
.caps-label { font-size: 0.6rem; color: #555; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.2rem; }
.caps-select {
  width: 100%; background: #1e1e3a; border: 1px solid #2a2a4a; border-radius: 4px;
  color: #e0e0e0; padding: 0.3rem; font-size: 0.7rem; outline: none;
}
.mcp-tool-item { font-size: 0.6rem; padding: 0.2rem; border-bottom: 1px solid #1a1a3a; }
.mcp-tool-name { color: #7c5cfc; font-weight: 600; }
.mcp-tool-desc { color: #666; display: block; }
.caps-textarea {
  background: #1e1e3a; border: 1px solid #2a2a4a; border-radius: 4px;
  color: #e0e0e0; padding: 0.3rem; font-size: 0.65rem; outline: none; resize: vertical;
  font-family: inherit; width: 100%;
}
.caps-textarea:focus { border-color: #7c5cfc; }
</style>

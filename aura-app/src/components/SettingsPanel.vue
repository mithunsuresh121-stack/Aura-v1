<script setup lang="ts">
import { ref, onMounted } from 'vue'

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
    terminalEnabled: boolean
  }
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'selectModel', model: string): void
}>()

// --- Tabs ---
const activeTab = ref<'permissions' | 'capabilities'>('permissions')

// --- Permissions ---
const permissions = ref<any[]>([])
const groups = ref<any[]>([])
const groupedView = ref(true)

async function loadPermissions() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/permissions`, { signal: AbortSignal.timeout(3000) })
    if (r.ok) {
      const d = await r.json()
      permissions.value = d.permissions || []
      groups.value = d.groups || []
    }
  } catch {}
}

async function grant(name: string) {
  try {
    await fetch(`${props.serverUrl}/v1/permissions/grant`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name}),
    })
    await loadPermissions()
  } catch {}
}

async function revoke(name: string) {
  try {
    await fetch(`${props.serverUrl}/v1/permissions/revoke`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name}),
    })
    await loadPermissions()
  } catch {}
}

async function togglePermission(p: any) {
  if (p.granted) { await revoke(p.name) } else { await grant(p.name) }
}

async function grantGroup(group: string) {
  try {
    await fetch(`${props.serverUrl}/v1/permissions/grant-group`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({group}),
    })
    await loadPermissions()
  } catch {}
}

async function revokeGroup(group: string) {
  try {
    await fetch(`${props.serverUrl}/v1/permissions/revoke-group`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({group}),
    })
    await loadPermissions()
  } catch {}
}

async function grantAll() {
  try {
    await fetch(`${props.serverUrl}/v1/permissions/grant-all`, { method: 'POST' })
    await loadPermissions()
  } catch {}
}

async function revokeAll() {
  try {
    await fetch(`${props.serverUrl}/v1/permissions/revoke-all`, { method: 'POST' })
    await loadPermissions()
  } catch {}
}

function permissionsByGroup(): { group: string; group_label: string; perms: any[] }[] {
  if (!groupedView.value) {
    return [{ group: 'all', group_label: 'All Permissions', perms: permissions.value }]
  }
  return groups.value.map((g: any) => ({
    ...g,
    perms: permissions.value.filter((p: any) => p.group === g.name),
  })).filter((g: any) => g.perms.length > 0)
}

function groupGranted(groupName: string): boolean {
  const groupPerms = permissions.value.filter((p: any) => p.group === groupName)
  return groupPerms.length > 0 && groupPerms.every((p: any) => p.granted)
}

function groupPartial(groupName: string): boolean {
  const groupPerms = permissions.value.filter((p: any) => p.group === groupName)
  const granted = groupPerms.filter((p: any) => p.granted)
  return granted.length > 0 && granted.length < groupPerms.length
}

// --- Capabilities sub-panel (inline controls) ---
const expanded = ref<Record<string, boolean>>({})
const toggle = (section: string) => { expanded.value[section] = !expanded.value[section] }

// Computer
const mousePos = ref({ x: 0, y: 0 })
const screenshotResult = ref('')
const lookResult = ref('')
const clickX = ref(500)
const clickY = ref(400)
const typeText = ref('')
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

// MCP
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

// Video
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



onMounted(loadPermissions)
</script>

<template>
  <div class="settings-overlay" @click.self="emit('close')">
    <div class="settings-modal">
      <div class="settings-header">
        <h2>Settings</h2>
        <button class="settings-close" @click="emit('close')">&times;</button>
      </div>

      <!-- Tabs -->
      <div class="settings-tabs">
        <button class="tab-btn" :class="{ active: activeTab === 'permissions' }" @click="activeTab = 'permissions'">
          Permissions
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'capabilities' }" @click="activeTab = 'capabilities'">
          Capabilities
        </button>
      </div>

      <!-- === PERMISSIONS TAB === -->
      <div v-if="activeTab === 'permissions'" class="settings-body">
        <div class="perms-toolbar">
          <label class="group-toggle-label">
            <input type="checkbox" v-model="groupedView" />
            <span>Group by category</span>
          </label>
          <div class="perms-bulk">
            <button class="btn-primary btn-sm" @click="grantAll">Grant All</button>
            <button class="btn-danger btn-sm" @click="revokeAll">Revoke All</button>
          </div>
        </div>

        <div v-for="g in permissionsByGroup()" :key="g.group" class="perms-group">
          <div class="perms-group-header">
            <span class="perms-group-label">{{ g.group_label }}</span>
            <span class="perms-group-count">{{ g.perms.filter(p => p.granted).length }}/{{ g.perms.length }}</span>
            <button class="btn-tiny" @click="grantGroup(g.group)" :disabled="groupGranted(g.group)">Grant Group</button>
            <button class="btn-tiny btn-tiny-danger" @click="revokeGroup(g.group)" :disabled="!groupGranted(g.group) && !groupPartial(g.group)">Revoke Group</button>
          </div>
          <div v-for="p in g.perms" :key="p.name" class="perm-item">
            <div class="perm-info">
              <span class="perm-label">{{ p.label }}</span>
              <span class="perm-purpose">{{ p.purpose }}</span>
              <span v-if="p.required_by.length" class="perm-required">Required by: {{ p.required_by.join(', ') }}</span>
            </div>
            <div class="perm-controls">
              <span class="perm-granted-at" v-if="p.granted_at">since {{ new Date(p.granted_at * 1000).toLocaleDateString() }}</span>
              <button
                class="perm-toggle"
                :class="{ granted: p.granted }"
                @click="togglePermission(p)"
              >
                {{ p.granted ? 'Granted' : 'Denied' }}
              </button>
            </div>
          </div>
        </div>

        <div v-if="permissions.length === 0" class="empty-state">
          No permissions defined.
        </div>
      </div>

      <!-- === CAPABILITIES TAB === -->
      <div v-if="activeTab === 'capabilities'" class="settings-body">
        <div class="caps-section">
          <div class="caps-header" @click="toggle('models')">
            <span class="caps-title">Model</span>
            <span class="caps-badge">{{ capabilities.activeModel }}</span>
            <span class="caps-arrow" v-html="expanded.models ? '&#9660;' : '&#9654;'"></span>
          </div>
          <div class="caps-body" v-if="expanded.models">
            <select v-model="capabilities.activeModel" @change="emit('selectModel', capabilities.activeModel)" class="input">
              <option v-for="m in capabilities.availableModels" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
        </div>

        <div class="caps-section">
          <div class="caps-header" @click="toggle('computer')">
            <span class="caps-title">Computer</span>
            <span class="caps-badge on" v-if="capabilities.computerEnabled">active</span>
            <span class="caps-badge" v-else>off</span>
            <span class="caps-arrow" v-html="expanded.computer ? '&#9660;' : '&#9654;'"></span>
          </div>
          <div class="caps-body" v-if="expanded.computer">
            <div class="caps-row"><button class="btn-sm" @click="getMousePos">Mouse Pos</button><span class="caps-val">x:{{ mousePos.x }} y:{{ mousePos.y }}</span></div>
            <div class="caps-row"><button class="btn-sm" @click="getWindow">Active Window</button><span class="caps-val">{{ windowName || '—' }}</span></div>
            <div class="caps-row"><button class="btn-sm" @click="takeScreenshot">Screenshot</button><span class="caps-val">{{ screenshotResult || '—' }}</span></div>
            <div class="caps-row"><button class="btn-sm" @click="look">Look</button></div>
            <div class="caps-val" v-if="lookResult">{{ lookResult }}</div>
            <div class="caps-inline">
              <input v-model.number="clickX" class="input input-sm" type="number" placeholder="x" />
              <input v-model.number="clickY" class="input input-sm" type="number" placeholder="y" />
              <button class="btn-sm" @click="doClick">Click</button>
            </div>
            <div class="caps-inline">
              <input v-model="typeText" class="input input-wide" placeholder="Type something..." />
              <button class="btn-sm" @click="doType">Type</button>
            </div>
          </div>
        </div>

        <div class="caps-section">
          <div class="caps-header" @click="toggle('mcp')">
            <span class="caps-title">MCP</span>
            <span class="caps-badge on" v-if="capabilities.mcpEnabled">active</span>
            <span class="caps-badge" v-else>off</span>
            <span class="caps-arrow" v-html="expanded.mcp ? '&#9660;' : '&#9654;'"></span>
          </div>
          <div class="caps-body" v-if="expanded.mcp">
            <button class="btn-sm" @click="listMcpTools">List Tools</button>
            <div v-for="t in mcpTools" :key="t.name" class="mcp-tool-item">
              <span class="mcp-tool-name">{{ t.server }} / {{ t.name }}</span>
              <span class="mcp-tool-desc">{{ t.description }}</span>
            </div>
            <div class="caps-inline">
              <input v-model="mcpToolName" class="input input-wide" placeholder="mcp_server_toolname" />
            </div>
            <div class="caps-inline">
              <input v-model="mcpArgs" class="input input-wide" placeholder='{"key":"value"}' />
              <button class="btn-sm" @click="callMcpTool">Call</button>
            </div>
            <div class="caps-val" v-if="mcpResult">{{ mcpResult }}</div>
          </div>
        </div>

        <div class="caps-section">
          <div class="caps-header" @click="toggle('orch')">
            <span class="caps-title">Orchestrator</span>
            <span class="caps-badge on" v-if="capabilities.orchestrationEnabled">active</span>
            <span class="caps-badge" v-else>off</span>
            <span class="caps-arrow" v-html="expanded.orch ? '&#9660;' : '&#9654;'"></span>
          </div>
          <div class="caps-body" v-if="expanded.orch">
            <div class="caps-label">Sub-Agent</div>
            <div class="caps-inline">
              <input v-model="agentId" class="input input-sm" placeholder="id" />
              <input v-model="agentRole" class="input input-sm" placeholder="role" />
              <button class="btn-sm" @click="registerAgent">Add</button>
            </div>
            <div class="caps-label">Task</div>
            <div class="caps-inline">
              <input v-model="orchTask" class="input input-wide" placeholder="Describe a complex task..." />
              <button class="btn-sm" :disabled="orchLoading" @click="runOrchestration">{{ orchLoading ? '...' : 'Go' }}</button>
            </div>
            <div class="caps-val" v-if="orchResult">{{ orchResult.slice(0, 200) }}...</div>
            <div v-if="subAgents.length" class="caps-val">Agents: {{ subAgents.map(a => a.id).join(', ') }}</div>
          </div>
        </div>

        <div class="caps-section">
          <div class="caps-header" @click="toggle('video')">
            <span class="caps-title">Video Edit</span>
            <span class="caps-badge on" v-if="capabilities.videoEnabled">{{ capabilities.availableEditors.join(', ') || 'active' }}</span>
            <span class="caps-badge" v-else>off</span>
            <span class="caps-arrow" v-html="expanded.video ? '&#9660;' : '&#9654;'"></span>
          </div>
          <div class="caps-body" v-if="expanded.video">
            <textarea v-model="editDesc" class="input textarea" placeholder="Describe the edit..." rows="2"></textarea>
            <input v-model="editOutput" class="input input-wide" placeholder="Output path" />
            <button class="btn-sm" :disabled="editLoading" @click="runEdit">{{ editLoading ? 'Running...' : 'Execute Edit' }}</button>
            <div class="caps-val" v-if="editResult">Status: {{ editResult.status }} — Actions: {{ editResult.actions?.join(', ') || '—' }}</div>
          </div>
        </div>


      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.7);
  backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 2000; padding: 1rem;
}
.settings-modal {
  background: linear-gradient(135deg, #111122, #0d0d1e);
  border: 1px solid rgba(30, 30, 54, 0.6);
  border-radius: 16px; width: 100%; max-width: 680px; max-height: 85vh;
  display: flex; flex-direction: column;
  box-shadow: 0 24px 80px rgba(0,0,0,0.5);
}
.settings-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 1rem 1.25rem; border-bottom: 1px solid rgba(30, 30, 54, 0.5);
}
.settings-header h2 { font-size: 1.05rem; color: #e8e8f0; margin: 0; font-weight: 600; }
.settings-close {
  background: none; border: none; color: #484860; font-size: 1.4rem;
  cursor: pointer; width: 32px; height: 32px; display: flex;
  align-items: center; justify-content: center; border-radius: 8px;
  transition: all 0.15s;
}
.settings-close:hover { background: rgba(255,255,255,0.04); color: #e8e8f0; }

.settings-tabs {
  display: flex; gap: 0; border-bottom: 1px solid rgba(30, 30, 54, 0.4);
  padding: 0 1.25rem;
}
.tab-btn {
  background: none; border: none; color: #484860; padding: 0.55rem 1rem;
  cursor: pointer; font-size: 0.78rem; border-bottom: 2px solid transparent;
  margin-bottom: -1px; font-family: inherit; transition: color 0.15s;
}
.tab-btn:hover { color: #8888a0; }
.tab-btn.active { color: #7c5cfc; border-bottom-color: #7c5cfc; }

.settings-body {
  flex: 1; overflow-y: auto; padding: 1rem 1.25rem;
  display: flex; flex-direction: column; gap: 0.4rem;
}

/* Bulk actions */
.perms-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.25rem;
}
.group-toggle-label {
  display: flex; align-items: center; gap: 0.35rem;
  font-size: 0.7rem; color: #686880; cursor: pointer;
}
.perms-bulk { display: flex; gap: 0.35rem; }

/* Permission group */
.perms-group {
  border: 1px solid rgba(30, 30, 54, 0.5); border-radius: 10px; overflow: hidden;
}
.perms-group-header {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.45rem 0.7rem; background: rgba(255,255,255,0.02);
  font-size: 0.7rem; font-weight: 600;
}
.perms-group-label { flex: 1; color: #9898b0; text-transform: uppercase; letter-spacing: 0.05em; }
.perms-group-count { font-size: 0.6rem; color: #484860; }

/* Permission item */
.perm-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.5rem 0.7rem; border-top: 1px solid rgba(30, 30, 54, 0.3);
  gap: 1rem; transition: background 0.15s;
}
.perm-item:hover { background: rgba(255,255,255,0.015); }
.perm-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.1rem; }
.perm-label { font-size: 0.75rem; color: #e8e8f0; font-weight: 500; }
.perm-purpose { font-size: 0.62rem; color: #585870; line-height: 1.3; }
.perm-required { font-size: 0.58rem; color: #c084fc; }
.perm-controls { display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0; }
.perm-granted-at { font-size: 0.58rem; color: #383848; white-space: nowrap; }

.perm-toggle {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(30, 30, 54, 0.4);
  border-radius: 6px; color: #484860; padding: 0.25rem 0.55rem; cursor: pointer;
  font-size: 0.62rem; font-weight: 600; min-width: 66px;
  font-family: inherit; transition: all 0.15s;
}
.perm-toggle.granted {
  background: rgba(74, 222, 128, 0.08); border-color: rgba(74, 222, 128, 0.3);
  color: #4ade80;
}
.perm-toggle:hover { opacity: 0.8; }

/* Capabilities inline */
.caps-section { border: 1px solid rgba(30, 30, 54, 0.5); border-radius: 10px; overflow: hidden; }
.caps-header {
  display: flex; align-items: center; gap: 0.4rem; padding: 0.45rem 0.7rem;
  cursor: pointer; background: rgba(255,255,255,0.02); user-select: none;
  transition: background 0.15s;
}
.caps-header:hover { background: rgba(255,255,255,0.04); }
.caps-title { font-size: 0.75rem; font-weight: 600; color: #9898b0; flex: 1; }
.caps-badge {
  font-size: 0.58rem; padding: 0.1rem 0.35rem; border-radius: 5px;
  background: rgba(255,255,255,0.03); color: #484860; text-transform: uppercase;
}
.caps-badge.on { background: rgba(74, 222, 128, 0.1); color: #4ade80; }
.caps-arrow { font-size: 0.5rem; color: #383848; }
.caps-body { padding: 0.4rem 0.7rem; display: flex; flex-direction: column; gap: 0.3rem; background: rgba(0,0,0,0.15); }
.caps-row { display: flex; align-items: center; gap: 0.35rem; }
.caps-inline { display: flex; gap: 0.25rem; align-items: center; }
.caps-val { font-size: 0.62rem; color: #585870; word-break: break-all; }
.caps-label { font-size: 0.58rem; color: #383848; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.15rem; }

.mcp-tool-item { font-size: 0.62rem; padding: 0.2rem; border-bottom: 1px solid rgba(30, 30, 54, 0.3); }
.mcp-tool-name { color: #7c5cfc; font-weight: 600; }
.mcp-tool-desc { color: #585870; display: block; }

.empty-state { text-align: center; padding: 2rem; color: #484860; font-size: 0.82rem; }

/* Shared */
.btn-primary { background: linear-gradient(135deg, #7c5cfc, #6a4ae0); border: none; color: #fff; padding: 0.35rem 0.7rem; border-radius: 8px; cursor: pointer; font-size: 0.7rem; font-family: inherit; }
.btn-primary:hover { opacity: 0.9; }
.btn-danger { background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); color: #ef4444; padding: 0.35rem 0.7rem; border-radius: 8px; cursor: pointer; font-size: 0.7rem; font-family: inherit; }
.btn-danger:hover { background: rgba(239, 68, 68, 0.18); }
.btn-sm { background: rgba(255,255,255,0.03); border: 1px solid rgba(30, 30, 54, 0.4); color: #686880; padding: 0.25rem 0.55rem; border-radius: 7px; cursor: pointer; font-size: 0.65rem; white-space: nowrap; font-family: inherit; transition: all 0.15s; }
.btn-sm:hover { background: rgba(255,255,255,0.06); color: #9898b0; }
.btn-sm:disabled { opacity: 0.3; cursor: default; }
.btn-tiny { background: rgba(255,255,255,0.03); border: none; color: #686880; padding: 0.2rem 0.45rem; border-radius: 5px; cursor: pointer; font-size: 0.62rem; font-family: inherit; transition: background 0.15s; }
.btn-tiny:hover:not(:disabled) { background: rgba(255,255,255,0.06); color: #9898b0; }
.btn-tiny:disabled { opacity: 0.2; cursor: default; }
.btn-tiny-danger:hover:not(:disabled) { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
.input {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(30, 30, 54, 0.4);
  border-radius: 7px; color: #e8e8f0; padding: 0.3rem 0.45rem;
  font-size: 0.7rem; outline: none; font-family: inherit;
  transition: border-color 0.2s;
}
.input:focus { border-color: rgba(124, 92, 252, 0.4); }
.input-sm { width: 72px; }
.input-wide { flex: 1; min-width: 0; }
.textarea { resize: vertical; width: 100%; font-family: inherit; background: rgba(255,255,255,0.02); }
</style>

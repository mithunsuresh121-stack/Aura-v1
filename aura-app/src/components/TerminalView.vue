<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import anser from 'anser'

const props = defineProps<{ serverUrl: string }>()

interface Session {
  id: string
  shell: string
  running: boolean
}

const sessions = ref<Session[]>([])
const activeSessionId = ref('')
const command = ref('')
const selectedShell = ref('bash')
const loading = ref(false)
const cmdHistory = ref<string[]>([])
const historyIndex = ref(-1)
const outputEl = ref<HTMLElement | null>(null)
const termCols = ref(80)
const termRows = ref(24)
const copied = ref(false)

// Per-session output store (keyed by session ID)
const outputs = new Map<string, string>()

const activeOutput = computed(() => {
  if (!activeSessionId.value) return ''
  return outputs.get(activeSessionId.value) || ''
})

function ansiToHtml(text: string): string {
  return anser.ansiToHtml(text, {
    use_classes: true,
    remove_empty: true,
  })
}

function appendOutput(sid: string, text: string) {
  const existing = outputs.get(sid) || ''
  outputs.set(sid, existing + text)
}

function clearActiveOutput() {
  if (activeSessionId.value) {
    outputs.set(activeSessionId.value, '')
  }
}

async function listSessions() {
  try {
    const r = await fetch(`${props.serverUrl}/v1/terminal/sessions`)
    const data = await r.json()
    sessions.value = (data.sessions || []).filter((s: any) => s.running)
    if (sessions.value.length > 0 && !activeSessionId.value) {
      activeSessionId.value = sessions.value[0].id
    }
  } catch {}
}

async function createSession() {
  loading.value = true
  try {
    const r = await fetch(`${props.serverUrl}/v1/terminal/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shell: selectedShell.value, rows: termRows.value, cols: termCols.value }),
    })
    const data = await r.json()
    await listSessions()
    if (data?.session_id) activeSessionId.value = data.session_id
  } catch {}
  loading.value = false
}

async function closeSession(id: string) {
  try {
    await fetch(`${props.serverUrl}/v1/terminal/${id}/close`, { method: 'POST' })
    outputs.delete(id)
    if (activeSessionId.value === id) activeSessionId.value = ''
    await listSessions()
  } catch {}
}

async function closeAllSessions() {
  for (const s of sessions.value) {
    try { await fetch(`${props.serverUrl}/v1/terminal/${s.id}/close`, { method: 'POST' }) } catch {}
  }
  outputs.clear()
  sessions.value = []
  activeSessionId.value = ''
}

async function execCommand() {
  const cmd = command.value.trim()
  if (!cmd) return
  if (!activeSessionId.value) await createSession()
  if (!activeSessionId.value) return

  cmdHistory.value.push(cmd)
  historyIndex.value = -1
  command.value = ''
  loading.value = true

  appendOutput(activeSessionId.value, `<span class="ansi-prompt">$ </span>${escapeHtml(cmd)}\n`)

  try {
    const r = await fetch(`${props.serverUrl}/v1/terminal/exec?session_id=${activeSessionId.value}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd, timeout: 30 }),
    })
    const data = await r.json()
    if (data.output) {
      appendOutput(activeSessionId.value, ansiToHtml(data.output) + '\n')
    } else if (data.error) {
      appendOutput(activeSessionId.value, `<span class="ansi-error">[error] ${escapeHtml(data.error)}</span>\n`)
    }
  } catch (e) {
    appendOutput(activeSessionId.value, `<span class="ansi-error">[error] ${e}</span>\n`)
  }
  loading.value = false
  await nextTick()
  scrollToBottom()
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    execCommand()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (cmdHistory.value.length === 0) return
    historyIndex.value = Math.min(historyIndex.value + 1, cmdHistory.value.length - 1)
    command.value = cmdHistory.value[cmdHistory.value.length - 1 - historyIndex.value]
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (historyIndex.value <= 0) {
      historyIndex.value = -1
      command.value = ''
      return
    }
    historyIndex.value = Math.max(historyIndex.value - 1, 0)
    command.value = cmdHistory.value[cmdHistory.value.length - 1 - historyIndex.value]
  }
}

function scrollToBottom() {
  if (outputEl.value) {
    outputEl.value.scrollTop = outputEl.value.scrollHeight
  }
}

function selectSession(id: string) {
  activeSessionId.value = id
}

async function copyOutput() {
  const text = activeOutput.value.replace(/<[^>]+>/g, '')
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => copied.value = false, 2000)
  } catch {}
}

const autoRefresh = ref<ReturnType<typeof setInterval> | null>(null)

onMounted(() => {
  listSessions()
  autoRefresh.value = setInterval(listSessions, 3000)
})

onUnmounted(() => {
  if (autoRefresh.value) clearInterval(autoRefresh.value)
})
</script>

<template>
  <div class="terminal-container">
    <div class="terminal-toolbar">
      <div class="toolbar-left">
        <select v-model="selectedShell" class="shell-select" :disabled="loading">
          <option value="bash">bash</option>
          <option value="zsh">zsh</option>
          <option value="powershell">powershell</option>
        </select>
        <button class="toolbar-btn" @click="createSession" :disabled="loading">
          + New Session
        </button>
        <button class="toolbar-btn" @click="closeAllSessions" :disabled="sessions.length === 0">
          Close All
        </button>
        <button class="toolbar-btn" @click="clearActiveOutput" :disabled="!activeSessionId">
          Clear
        </button>
      </div>
      <div class="toolbar-right">
        <div class="resize-controls">
          <label class="resize-label" title="Columns">
            Cols <input v-model.number="termCols" class="resize-input" type="number" min="20" max="400" />
          </label>
          <label class="resize-label" title="Rows">
            Rows <input v-model.number="termRows" class="resize-input" type="number" min="5" max="200" />
          </label>
        </div>
        <span class="session-count">{{ sessions.length }} session{{ sessions.length !== 1 ? 's' : '' }}</span>
      </div>
    </div>

    <div class="terminal-sessions" v-if="sessions.length > 0">
      <button
        v-for="s in sessions"
        :key="s.id"
        class="session-tab"
        :class="{ active: s.id === activeSessionId }"
        @click="selectSession(s.id)"
      >
        <span class="session-tab-shell">{{ s.shell }}</span>
        <span class="session-tab-id">{{ s.id.slice(0, 8) }}</span>
        <span class="session-tab-dot" :class="{ alive: s.running }"></span>
        <span class="session-tab-close" @click.stop="closeSession(s.id)">&times;</span>
      </button>
    </div>

    <div class="terminal-output" ref="outputEl" v-if="activeSessionId">
      <div class="output-header">
        <span class="output-session-label">{{ activeSessionId.slice(0, 8) }}@{{ sessions.find(s => s.id === activeSessionId)?.shell || '?' }}</span>
        <button class="output-btn" @click="copyOutput">{{ copied ? 'Copied!' : 'Copy Output' }}</button>
      </div>
      <div v-if="activeOutput" class="output-content" v-html="activeOutput"></div>
      <div v-else class="output-placeholder">Ready. Type a command and press Enter.</div>
    </div>
    <div class="terminal-output terminal-output-empty" v-else>
      <div class="output-placeholder">Create a session to get started.</div>
    </div>

    <div class="terminal-input-row">
      <span class="input-prompt">$</span>
      <input
        v-model="command"
        class="terminal-input"
        placeholder="Type a command..."
        @keydown="onKeydown"
        :disabled="loading || !activeSessionId"
      />
      <button class="toolbar-btn run-btn" @click="execCommand" :disabled="loading || !command.trim() || !activeSessionId">
        {{ loading ? '...' : 'Run' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.terminal-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0c0c1a;
  border-radius: 0;
  overflow: hidden;
}

.terminal-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.75rem;
  background: rgba(18, 18, 34, 0.6);
  border-bottom: 1px solid rgba(30, 30, 54, 0.4);
  gap: 0.5rem;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.resize-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.resize-label {
  display: flex;
  align-items: center;
  gap: 0.2rem;
  font-size: 0.58rem;
  color: #484860;
}

.resize-input {
  width: 40px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(30, 30, 54, 0.4);
  border-radius: 5px;
  color: #9898b0;
  padding: 0.1rem 0.2rem;
  font-size: 0.6rem;
  outline: none;
  font-family: inherit;
  text-align: center;
}
.resize-input:focus {
  border-color: rgba(124, 92, 252, 0.4);
}
.resize-input::-webkit-inner-spin-button {
  opacity: 0.3;
}

.shell-select {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(30, 30, 54, 0.5);
  border-radius: 7px;
  color: #9898b0;
  padding: 0.25rem 0.5rem;
  font-size: 0.68rem;
  outline: none;
  font-family: inherit;
  cursor: pointer;
}
.shell-select:focus {
  border-color: rgba(124, 92, 252, 0.4);
}

.toolbar-btn {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(30, 30, 54, 0.4);
  border-radius: 7px;
  color: #686880;
  padding: 0.25rem 0.55rem;
  cursor: pointer;
  font-size: 0.65rem;
  font-family: inherit;
  white-space: nowrap;
  transition: all 0.15s;
}
.toolbar-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
  color: #9898b0;
}
.toolbar-btn:disabled {
  opacity: 0.3;
  cursor: default;
}

.session-count {
  font-size: 0.62rem;
  color: #484860;
  white-space: nowrap;
}

.terminal-sessions {
  display: flex;
  gap: 0.15rem;
  padding: 0.2rem 0.75rem;
  background: rgba(0, 0, 0, 0.15);
  border-bottom: 1px solid rgba(30, 30, 54, 0.3);
  overflow-x: auto;
  flex-shrink: 0;
}

.session-tab {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(30, 30, 54, 0.3);
  border-radius: 6px;
  padding: 0.2rem 0.45rem;
  cursor: pointer;
  font-size: 0.62rem;
  font-family: inherit;
  color: #585870;
  transition: all 0.12s;
  flex-shrink: 0;
}
.session-tab:hover {
  background: rgba(255, 255, 255, 0.04);
  color: #8888a0;
}
.session-tab.active {
  background: rgba(124, 92, 252, 0.08);
  border-color: rgba(124, 92, 252, 0.25);
  color: #c084fc;
}
.session-tab-shell {
  font-weight: 600;
  text-transform: uppercase;
  font-size: 0.55rem;
}
.session-tab-id {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 0.58rem;
}
.session-tab-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #383848;
}
.session-tab-dot.alive {
  background: #4ade80;
  box-shadow: 0 0 4px rgba(74, 222, 128, 0.4);
}
.session-tab-close {
  font-size: 0.7rem;
  color: #383848;
  margin-left: 0.1rem;
  line-height: 1;
}
.session-tab-close:hover {
  color: #ef4444;
}

.terminal-output {
  flex: 1;
  overflow-y: auto;
  padding: 0;
  background: rgba(0, 0, 0, 0.2);
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 0.72rem;
  line-height: 1.5;
  color: #a0a0b8;
  display: flex;
  flex-direction: column;
}

.output-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.25rem 0.75rem;
  background: rgba(0, 0, 0, 0.15);
  border-bottom: 1px solid rgba(30, 30, 54, 0.2);
  flex-shrink: 0;
}

.output-session-label {
  font-size: 0.6rem;
  color: #484860;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.output-btn {
  background: none;
  border: 1px solid rgba(30, 30, 54, 0.3);
  border-radius: 5px;
  color: #484860;
  padding: 0.1rem 0.4rem;
  cursor: pointer;
  font-size: 0.58rem;
  font-family: inherit;
  transition: all 0.12s;
}
.output-btn:hover {
  color: #8888a0;
  border-color: rgba(30, 30, 54, 0.5);
}

.output-content {
  padding: 0.5rem 0.75rem;
  flex: 1;
}

.output-placeholder {
  padding: 0.5rem 0.75rem;
  color: #383848;
  font-style: italic;
  font-size: 0.72rem;
}

/* ANSI classes — generated by anser */
:deep(.ansi-black) { color: #1e1e1e; }
:deep(.ansi-black-fg) { color: #1e1e1e; }
:deep(.ansi-red) { color: #f44; }
:deep(.ansi-red-fg) { color: #f44; }
:deep(.ansi-green) { color: #4ade80; }
:deep(.ansi-green-fg) { color: #4ade80; }
:deep(.ansi-yellow) { color: #facc15; }
:deep(.ansi-yellow-fg) { color: #facc15; }
:deep(.ansi-blue) { color: #60a5fa; }
:deep(.ansi-blue-fg) { color: #60a5fa; }
:deep(.ansi-magenta) { color: #c084fc; }
:deep(.ansi-magenta-fg) { color: #c084fc; }
:deep(.ansi-cyan) { color: #22d3ee; }
:deep(.ansi-cyan-fg) { color: #22d3ee; }
:deep(.ansi-white) { color: #d0d0d0; }
:deep(.ansi-white-fg) { color: #d0d0d0; }
:deep(.ansi-bright-black) { color: #484860; }
:deep(.ansi-bright-black-fg) { color: #484860; }
:deep(.ansi-bright-red) { color: #f66; }
:deep(.ansi-bright-red-fg) { color: #f66; }
:deep(.ansi-bright-green) { color: #6ee7b7; }
:deep(.ansi-bright-green-fg) { color: #6ee7b7; }
:deep(.ansi-bright-yellow) { color: #fde047; }
:deep(.ansi-bright-yellow-fg) { color: #fde047; }
:deep(.ansi-bright-blue) { color: #93c5fd; }
:deep(.ansi-bright-blue-fg) { color: #93c5fd; }
:deep(.ansi-bright-magenta) { color: #d8b4fe; }
:deep(.ansi-bright-magenta-fg) { color: #d8b4fe; }
:deep(.ansi-bright-cyan) { color: #67e8f9; }
:deep(.ansi-bright-cyan-fg) { color: #67e8f9; }
:deep(.ansi-bright-white) { color: #fff; }
:deep(.ansi-bright-white-fg) { color: #fff; }
:deep(.ansi-bg-black) { background: #1e1e1e; }
:deep(.ansi-bg-red) { background: #f44; }
:deep(.ansi-bg-green) { background: #4ade80; }
:deep(.ansi-bg-yellow) { background: #facc15; }
:deep(.ansi-bg-blue) { background: #60a5fa; }
:deep(.ansi-bg-magenta) { background: #c084fc; }
:deep(.ansi-bg-cyan) { background: #22d3ee; }
:deep(.ansi-bg-white) { background: #d0d0d0; }

.ansi-prompt {
  color: #4ade80;
  font-weight: 700;
}

.ansi-error {
  color: #f44;
}

.terminal-input-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.75rem;
  background: rgba(0, 0, 0, 0.3);
  border-top: 1px solid rgba(30, 30, 54, 0.4);
  flex-shrink: 0;
}

.input-prompt {
  color: #4ade80;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 0.75rem;
  font-weight: 700;
  flex-shrink: 0;
}

.terminal-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #e0e0f0;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 0.75rem;
  padding: 0.2rem 0;
}
.terminal-input::placeholder {
  color: #383848;
}

.run-btn {
  flex-shrink: 0;
}
</style>

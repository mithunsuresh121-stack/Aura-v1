<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { marked } from 'marked'

const props = defineProps<{
  serverUrl: string
  connected: boolean
}>()

interface ToolSuggestion {
  name: string
  args: string[]
  display: string
  description: string
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  toolSuggestions?: ToolSuggestion[]
}

interface Conversation {
  id: string
  title: string
  messages: Message[]
  createdAt: number
  updatedAt: number
}

const STORAGE_KEY = 'cortex_conversations'
const ACTIVE_KEY = 'cortex_active_conversation'

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveConversations() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.value))
}

function loadActiveId(): string | null {
  return localStorage.getItem(ACTIVE_KEY)
}

function saveActiveId(id: string | null) {
  if (id) localStorage.setItem(ACTIVE_KEY, id)
  else localStorage.removeItem(ACTIVE_KEY)
}

const conversations = ref<Conversation[]>(loadConversations())
const activeId = ref<string | null>(loadActiveId())
const messages = ref<Message[]>([])
const input = ref('')
const task = ref('')
const loading = ref(false)
const chatEnd = ref<HTMLElement | null>(null)
const abortController = ref<AbortController | null>(null)
const agentMode = ref(false)
const agentState = ref<Record<string, any> | null>(null)
const showSidebar = ref(false)
const temperature = ref(0.7)
const topP = ref(1.0)

function getActive(): Conversation | undefined {
  return conversations.value.find(c => c.id === activeId.value)
}

function activateConversation(id: string) {
  if (loading.value) return
  saveCurrentMessages()
  if (!conversations.value.find(c => c.id === id)) return
  activeId.value = id
  saveActiveId(id)
  const conv = getActive()
  messages.value = conv ? JSON.parse(JSON.stringify(conv.messages)) : []
  nextTick(scrollToBottom)
}

function newConversation() {
  if (loading.value) return
  saveCurrentMessages()
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
  const conv: Conversation = {
    id,
    title: 'New conversation',
    messages: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }
  conversations.value.unshift(conv)
  activeId.value = id
  saveActiveId(id)
  messages.value = []
  saveConversations()
  showSidebar.value = false
}

function deleteConversation(id: string) {
  if (loading.value) return
  const idx = conversations.value.findIndex(c => c.id === id)
  if (idx === -1) return
  conversations.value.splice(idx, 1)
  saveConversations()
  if (activeId.value === id) {
    if (conversations.value.length > 0) {
      activateConversation(conversations.value[0].id)
    } else {
      activeId.value = null
      saveActiveId(null)
      messages.value = []
    }
  }
}

function saveCurrentMessages() {
  if (!activeId.value) return
  const conv = getActive()
  if (!conv) return
  conv.messages = JSON.parse(JSON.stringify(messages.value.filter(m => !m.streaming)))
  conv.updatedAt = Date.now()
  const firstUser = conv.messages.find(m => m.role === 'user')
  if (firstUser && conv.title === 'New conversation') {
    conv.title = firstUser.content.slice(0, 40) + (firstUser.content.length > 40 ? '...' : '')
  }
  saveConversations()
}

function scrollToBottom() {
  nextTick(() => chatEnd.value?.scrollIntoView({ behavior: 'smooth' }))
}

function updateTitleFromMessage(text: string) {
  const conv = getActive()
  if (!conv || conv.title !== 'New conversation') return
  conv.title = text.slice(0, 40) + (text.length > 40 ? '...' : '')
  saveConversations()
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return

  if (!activeId.value) newConversation()
  updateTitleFromMessage(text)

  input.value = ''
  messages.value.push({ role: 'user', content: text })
  const assistantMsg: Message = { role: 'assistant', content: '', streaming: true }
  messages.value.push(assistantMsg)
  loading.value = true
  scrollToBottom()

  abortController.value = new AbortController()

  try {
    const endpoint = agentMode.value ? '/v1/agent/chat' : '/v1/chat/completions'
    const payload: Record<string, any> = {
      messages: messages.value
        .filter(m => m !== assistantMsg)
        .map(m => ({ role: m.role, content: m.content })),
      stream: true,
      max_tokens: 256,
      temperature: temperature.value,
      top_p: topP.value,
    }
    if (agentMode.value) payload.model = 'cortex-agent'
    if (task.value.trim()) payload.task = task.value.trim()

    const response = await fetch(`${props.serverUrl}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: abortController.value.signal,
    })

    if (!response.ok) {
      const errData = await response.json().catch(() => null)
      assistantMsg.content = `Error: ${response.status} ${errData?.detail || response.statusText}`
      assistantMsg.streaming = false
      loading.value = false
      return
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data: ')) continue
        const data = trimmed.slice(6)
        if (data === '[DONE]') continue
        try {
          const parsed = JSON.parse(data)
          const delta = parsed.choices?.[0]?.delta?.content
          if (delta) { assistantMsg.content += delta; scrollToBottom() }
          // Handle tool suggestions (suggest then wait)
          if (parsed.tool_suggestions) {
            assistantMsg.toolSuggestions = parsed.tool_suggestions
            assistantMsg.streaming = false
          }
        } catch { }
      }
    }
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      assistantMsg.content = `Connection error: ${err.message}`
    }
  }

  assistantMsg.streaming = false
  loading.value = false
  scrollToBottom()
  abortController.value = null
  saveCurrentMessages()
}

async function executeToolSuggestion(msg: Message, suggestion: ToolSuggestion) {
  msg.toolSuggestions = undefined
  const toolMsg: Message = { role: 'assistant', content: `[TOOL RESULT: Running ${suggestion.display}...]`, streaming: true }
  messages.value.push(toolMsg)
  scrollToBottom()
  try {
    const response = await fetch(`${props.serverUrl}/v1/agent/tool/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool_name: suggestion.name,
        tool_args: suggestion.args,
        context_text: msg.content,
        temperature: temperature.value,
        top_p: topP.value,
      }),
    })
    if (!response.ok) {
      toolMsg.content = `[TOOL RESULT: Error ${response.status}]`
      toolMsg.streaming = false
      return
    }
    const data = await response.json()
    toolMsg.content = data.result
  } catch (err: any) {
    toolMsg.content = `[TOOL RESULT: Error: ${err.message}]`
  }
  toolMsg.streaming = false
  scrollToBottom()
  saveCurrentMessages()
}

function stopGeneration() {
  abortController.value?.abort()
}

function clearChat() {
  messages.value = []
  saveCurrentMessages()
}

function exportConversation() {
  const text = messages.value.map(m =>
    `## ${m.role === 'user' ? 'User' : 'Assistant'}\n${m.content}`
  ).join('\n\n')
  const blob = new Blob([text], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `cortex-conversation-${Date.now()}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function handleMessageClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  const codeBlock = target.closest('pre') || target.closest('code')
  if (!codeBlock) return
  const text = codeBlock.textContent || ''
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.createElement('span')
    btn.textContent = 'Copied!'
    btn.className = 'copy-toast'
    codeBlock.parentNode?.insertBefore(btn, codeBlock.nextSibling)
    setTimeout(() => btn.remove(), 1500)
  }).catch(() => {})
}

async function toggleAgentMode() {
  agentMode.value = !agentMode.value
  if (!agentMode.value) { agentState.value = null; return }
  try {
    const r = await fetch(`${props.serverUrl}/v1/agent/state`, { signal: AbortSignal.timeout(3000) })
    if (r.ok) agentState.value = await r.json()
  } catch { }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && loading.value) {
    stopGeneration()
    return
  }
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
    e.preventDefault()
    sendMessage()
  }
}

function renderMarkdown(text: string): string {
  let html = text
    .replace(
      /\[TOOL:\s*(\w+)\(([^)]*)\)\]/g,
      (_, name, args) => `<span class="tool-call">
        <span class="tool-call-icon">&#9881;</span>
        <span class="tool-call-name">${name}</span>
        <span class="tool-call-args">${args || '…'}</span>
      </span>`
    )
    .replace(
      /\[TOOL RESULT:\s*([^\]]+)\]/g,
      (_, result) => `<span class="tool-result">${result}</span>`
    )
  return marked.parse(html, { async: false }) as string
}

// Restore active conversation on mount
const initialConv = getActive()
if (initialConv) {
  messages.value = JSON.parse(JSON.stringify(initialConv.messages))
}
</script>

<template>
  <div class="chat-container">
    <header class="chat-header">
      <div class="header-left">
        <button class="btn-icon" @click="showSidebar = !showSidebar" title="Conversations">
          &#9776;
        </button>
        <div class="mode-toggle" @click="toggleAgentMode">
          <span class="mode-option" :class="{ active: !agentMode }">Cortex</span>
          <span class="mode-option" :class="{ active: agentMode }">Agent</span>
        </div>
        <input
          v-model="task"
          class="task-input"
          placeholder="LoRA task (optional)"
          :disabled="loading"
        />
      </div>
      <div class="header-actions">
        <div class="slider-group" title="Temperature">
          <label class="slider-label">Temp</label>
          <input type="range" v-model.number="temperature" min="0" max="2" step="0.05" class="slider" />
          <span class="slider-value">{{ temperature.toFixed(2) }}</span>
        </div>
        <div class="slider-group" title="Top-p sampling">
          <label class="slider-label">Top-p</label>
          <input type="range" v-model.number="topP" min="0" max="1" step="0.05" class="slider" />
          <span class="slider-value">{{ topP.toFixed(2) }}</span>
        </div>
        <span v-if="agentMode && agentState" class="agent-badge" :class="agentState.status">
          {{ agentState.status }}
        </span>
        <button class="btn-icon" @click="exportConversation" title="Export conversation" :disabled="messages.length === 0">
          &#8615;
        </button>
        <button class="btn-secondary" @click="newConversation">+ New</button>
        <button class="btn-secondary" @click="clearChat" :disabled="messages.length === 0">
          Clear
        </button>
      </div>
    </header>

    <div class="chat-body">
      <div class="conv-sidebar" v-if="showSidebar">
        <div class="conv-list">
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="conv-item"
            :class="{ active: conv.id === activeId }"
            @click="activateConversation(conv.id)"
          >
            <span class="conv-title">{{ conv.title }}</span>
            <span class="conv-meta">{{ conv.messages.length }} msgs</span>
            <button class="btn-del" @click.stop="deleteConversation(conv.id)" title="Delete">&#10005;</button>
          </div>
          <div v-if="conversations.length === 0" class="conv-empty">No conversations yet</div>
        </div>
      </div>
      <div class="chat-main">
        <div class="messages" v-if="messages.length > 0" @click="handleMessageClick">
          <div
            v-for="(msg, i) in messages"
            :key="i"
            class="message"
            :class="msg.role"
          >
            <div class="avatar">{{ msg.role === 'user' ? 'U' : 'C' }}</div>
            <div class="bubble">
              <div class="content" v-if="!msg.streaming || msg.content" v-html="renderMarkdown(msg.content)"></div>
              <div v-if="msg.toolSuggestions" class="tool-suggestions">
                <div v-for="(s, si) in msg.toolSuggestions" :key="si" class="tool-suggestion-item">
                  <span class="tool-suggestion-icon">&#9881;</span>
                  <span class="tool-suggestion-name">{{ s.display }}</span>
                  <span class="tool-suggestion-desc">{{ s.description }}</span>
                  <button class="btn-run-tool" @click="executeToolSuggestion(msg, s)" :disabled="loading">
                    Run
                  </button>
                </div>
              </div>
              <div class="cursor" v-if="msg.streaming">&#9612;</div>
            </div>
          </div>
          <div ref="chatEnd"></div>
        </div>

        <div class="empty-state" v-else>
          <div class="empty-icon">&#9670;</div>
          <template v-if="!connected">
            <p>Server disconnected</p>
            <p class="empty-hint">Start the server with:</p>
            <code class="startup-cmd">bash start.sh</code>
            <p class="empty-hint">or manually:</p>
            <code class="startup-cmd">python3 cortex-core/src/server/main.py</code>
            <p class="empty-hint">Reconnecting every 5 seconds...</p>
          </template>
          <template v-else>
            <p>Start a conversation with Cortex</p>
            <p class="empty-hint">Press <kbd>Cmd+Enter</kbd> to send</p>
          </template>
        </div>
      </div>
    </div>

    <div class="input-area">
      <textarea
        v-model="input"
        @keydown="handleKeydown"
        placeholder="Type a message...  (Cmd+Enter to send)"
        :disabled="loading || !connected"
        rows="1"
      ></textarea>
      <button
        v-if="!loading"
        class="btn-primary"
        @click="sendMessage"
        :disabled="!input.trim() || !connected"
      >
        Send
      </button>
      <button v-else class="btn-danger" @click="stopGeneration">
        Stop
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-container {
  display: flex; flex-direction: column; height: 100%;
}

.chat-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.75rem 1.5rem; border-bottom: 1px solid #2a2a4a;
}
.chat-header h2 { font-size: 1rem; font-weight: 600; margin: 0; }
.header-left { display: flex; align-items: center; gap: 0.5rem; flex: 1; }
.header-actions { display: flex; align-items: center; gap: 0.4rem; }

.btn-icon {
  background: none; border: 1px solid #2a2a4a; border-radius: 6px;
  color: #888; cursor: pointer; padding: 0.3rem 0.5rem; font-size: 1rem;
  line-height: 1;
}
.btn-icon:hover { background: #2a2a4a; color: #e0e0e0; }

.chat-body {
  flex: 1; display: flex; overflow: hidden;
}

.conv-sidebar {
  width: 200px; border-right: 1px solid #2a2a4a;
  background: #12122a; overflow-y: auto; flex-shrink: 0;
}
.conv-list { padding: 0.5rem; display: flex; flex-direction: column; gap: 0.3rem; }
.conv-item {
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.4rem 0.5rem; border-radius: 6px; cursor: pointer;
  font-size: 0.75rem;
}
.conv-item:hover { background: #1e1e3a; }
.conv-item.active { background: #2a2a4a; border: 1px solid #7c5cfc; }
.conv-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #a0a0c0; }
.conv-meta { font-size: 0.65rem; color: #555; flex-shrink: 0; }
.btn-del { background: none; border: none; color: #555; cursor: pointer; font-size: 0.7rem; padding: 0; }
.btn-del:hover { color: #ef4444; }
.conv-empty { color: #555; font-size: 0.75rem; text-align: center; padding: 1rem; }

.chat-main {
  flex: 1; display: flex; flex-direction: column; overflow: hidden;
}

.mode-toggle {
  display: flex; background: #12122a; border-radius: 8px; overflow: hidden;
  border: 1px solid #2a2a4a; cursor: pointer; flex-shrink: 0;
}
.mode-option {
  padding: 0.3rem 0.7rem; font-size: 0.75rem; font-weight: 600;
  color: #666; transition: all 0.15s; letter-spacing: 0.03em;
}
.mode-option.active { background: #7c5cfc; color: white; }
.mode-option:not(.active):hover { color: #a0a0c0; }

.agent-badge {
  font-size: 0.7rem; padding: 0.2rem 0.5rem; border-radius: 4px;
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
}
.agent-badge.active { background: #16553a; color: #4ade80; }
.agent-badge.disabled { background: #3a1a1a; color: #ef4444; }
.task-input {
  background: #1e1e3a; border: 1px solid #2a2a4a; border-radius: 6px;
  color: #a0a0c0; padding: 0.35rem 0.6rem; font-size: 0.75rem;
  width: 180px; outline: none; font-family: inherit;
}
.task-input:focus { border-color: #7c5cfc; color: #e0e0e0; }
.task-input:disabled { opacity: 0.4; }
.task-input::placeholder { color: #555; }
.btn-secondary {
  background: #2a2a4a; border: none; color: #888; padding: 0.4rem 0.8rem;
  border-radius: 6px; cursor: pointer; font-size: 0.8rem;
}
.btn-secondary:disabled { opacity: 0.3; cursor: default; }
.btn-secondary:hover:not(:disabled) { background: #3a3a5a; }

.slider-group {
  display: flex; align-items: center; gap: 0.3rem;
  background: #12122a; border-radius: 6px; padding: 0.15rem 0.4rem;
  border: 1px solid #2a2a4a;
}
.slider-label { font-size: 0.65rem; color: #666; text-transform: uppercase; letter-spacing: 0.03em; }
.slider { width: 60px; height: 4px; accent-color: #7c5cfc; cursor: pointer; }
.slider-value { font-size: 0.7rem; color: #a0a0c0; min-width: 28px; text-align: center; font-family: monospace; }

.copy-toast {
  position: absolute; right: 0.5rem; top: 0.5rem;
  background: #16553a; color: #4ade80; padding: 0.15rem 0.4rem;
  border-radius: 4px; font-size: 0.7rem; font-weight: 600;
  pointer-events: none;
}

.messages {
  flex: 1; overflow-y: auto; padding: 1.5rem;
  display: flex; flex-direction: column; gap: 1rem;
}
.message { display: flex; gap: 0.75rem; align-items: flex-start; }
.message.user { flex-direction: row-reverse; }

.avatar {
  width: 32px; height: 32px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.8rem; font-weight: 700; flex-shrink: 0;
}
.message.assistant .avatar { background: #7c5cfc; color: white; }
.message.user .avatar { background: #3b82f6; color: white; }

.bubble {
  max-width: 75%; padding: 0.75rem 1rem; border-radius: 12px;
  line-height: 1.5; font-size: 0.9rem;
  overflow-wrap: break-word; word-wrap: break-word; word-break: break-word;
}
.message.assistant .bubble { background: #1e1e3a; border: 1px solid #2a2a4a; }
.message.user .bubble { background: #3b82f6; color: white; }

.content :deep(p) { margin: 0.5rem 0; }
.content :deep(p:first-child) { margin-top: 0; }
.content :deep(p:last-child) { margin-bottom: 0; }
.content :deep(code) { background: #2a2a4a; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
.content :deep(pre) { background: #12122a; padding: 1rem; border-radius: 8px; overflow-x: auto; margin: 0.5rem 0; position: relative; }
.content :deep(pre code) { background: none; padding: 0; }
.content :deep(ul), .content :deep(ol) { padding-left: 1.5rem; margin: 0.5rem 0; }

:deep(.tool-call) {
  display: inline-flex; align-items: center; gap: 0.3rem;
  background: #2a2a4a; border: 1px solid #7c5cfc; border-radius: 6px;
  padding: 0.15rem 0.5rem; margin: 0 0.15rem;
  font-size: 0.8rem; font-family: var(--mono, monospace);
  vertical-align: middle;
}
:deep(.tool-call-icon) { color: #7c5cfc; font-size: 0.7rem; }
:deep(.tool-call-name) { color: #c084fc; font-weight: 600; }
:deep(.tool-call-args) { color: #888; }
:deep(.tool-result) {
  display: block; background: #12122a; border: 1px solid #3a3a5a;
  border-radius: 6px; padding: 0.4rem 0.6rem; margin: 0.4rem 0;
  font-size: 0.8rem; color: #a0a0c0; font-family: var(--mono, monospace);
  white-space: pre-wrap; word-break: break-all;
}

.tool-suggestions {
  display: flex; flex-direction: column; gap: 0.4rem; margin-top: 0.5rem;
  border-top: 1px solid #2a2a4a; padding-top: 0.5rem;
}
.tool-suggestion-item {
  display: flex; align-items: center; gap: 0.4rem;
  background: #12122a; border: 1px solid #3a3a5a; border-radius: 6px;
  padding: 0.4rem 0.6rem; font-size: 0.8rem;
}
.tool-suggestion-icon { color: #7c5cfc; font-size: 0.75rem; }
.tool-suggestion-name { color: #c084fc; font-weight: 600; font-family: var(--mono, monospace); }
.tool-suggestion-desc { color: #666; flex: 1; font-size: 0.75rem; }
.btn-run-tool {
  background: #16553a; border: none; color: #4ade80; padding: 0.2rem 0.6rem;
  border-radius: 4px; cursor: pointer; font-size: 0.7rem; font-weight: 600;
}
.btn-run-tool:hover:not(:disabled) { background: #1a6b48; }
.btn-run-tool:disabled { opacity: 0.4; cursor: default; }

.cursor { animation: blink 1s step-end infinite; color: #7c5cfc; }
@keyframes blink { 50% { opacity: 0; } }

.empty-state {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 0.5rem; color: #555;
}
.empty-icon { font-size: 3rem; color: #7c5cfc; opacity: 0.3; }
.empty-hint { font-size: 0.8rem; }
.startup-cmd {
  display: block; background: #12122a; border: 1px solid #2a2a4a; border-radius: 6px;
  padding: 0.4rem 0.8rem; font-size: 0.75rem; color: #a0a0c0;
  font-family: monospace; margin: 0.3rem 0;
}

.input-area {
  display: flex; gap: 0.5rem; padding: 1rem 1.5rem;
  border-top: 1px solid #2a2a4a; background: #16162a;
}
textarea {
  flex: 1; background: #1e1e3a; border: 1px solid #2a2a4a; border-radius: 8px;
  color: #e0e0e0; padding: 0.75rem; font-size: 0.9rem; resize: none;
  outline: none; font-family: inherit; max-height: 150px;
}
textarea:focus { border-color: #7c5cfc; }
textarea:disabled { opacity: 0.4; }

.btn-primary {
  background: #7c5cfc; border: none; color: white; padding: 0.75rem 1.25rem;
  border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 0.85rem;
}
.btn-primary:disabled { opacity: 0.3; cursor: default; }
.btn-primary:hover:not(:disabled) { background: #6a4ae0; }

.btn-danger {
  background: #ef4444; border: none; color: white; padding: 0.75rem 1.25rem;
  border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 0.85rem;
}
.btn-danger:hover { background: #dc2626; }
</style>
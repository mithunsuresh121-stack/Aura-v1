<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { marked } from 'marked'
import BuildPanel from './BuildPanel.vue'

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

const STORAGE_KEY = 'aura_conversations'
const ACTIVE_KEY = 'aura_active_conversation'

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
const buildMode = ref(false)
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
    if (agentMode.value) payload.model = 'aura-agent'
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
  a.download = `aura-conversation-${Date.now()}.md`
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
        <div class="mode-toggle">
          <span class="mode-option" :class="{ active: !agentMode && !buildMode }" @click="agentMode=false;buildMode=false">Chat</span>
          <span class="mode-option" :class="{ active: buildMode }" @click="buildMode=!buildMode;agentMode=false">Build</span>
          <span class="mode-option" :class="{ active: agentMode }" @click="agentMode=!agentMode;buildMode=false">Agent</span>
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
      <BuildPanel v-if="buildMode" :server-url="serverUrl" />
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
            <code class="startup-cmd">python3 aura-core/src/server/main.py</code>
            <p class="empty-hint">Reconnecting every 5 seconds...</p>
          </template>
          <template v-else>
            <p>Start a conversation with AURA</p>
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
  padding: 0.65rem 1.25rem;
  background: rgba(8, 8, 18, 0.6);
  border-bottom: 1px solid rgba(30, 30, 54, 0.5);
  backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
}
.header-left { display: flex; align-items: center; gap: 0.5rem; flex: 1; }
.header-actions { display: flex; align-items: center; gap: 0.35rem; }

.btn-icon {
  background: none; border: 1px solid rgba(30, 30, 54, 0.5); border-radius: 8px;
  color: #686880; cursor: pointer; padding: 0.3rem 0.45rem; font-size: 0.9rem;
  line-height: 1; transition: all 0.15s;
}
.btn-icon:hover { background: rgba(255,255,255,0.04); border-color: rgba(124, 92, 252, 0.3); color: #e8e8f0; }

.chat-body {
  flex: 1; display: flex; overflow: hidden;
}

.conv-sidebar {
  width: 220px; border-right: 1px solid rgba(30, 30, 54, 0.4);
  background: rgba(10, 10, 20, 0.5); overflow-y: auto; flex-shrink: 0;
}
.conv-list { padding: 0.5rem; display: flex; flex-direction: column; gap: 0.2rem; }
.conv-item {
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.35rem 0.5rem; border-radius: 8px; cursor: pointer;
  font-size: 0.72rem; transition: all 0.15s;
}
.conv-item:hover { background: rgba(255,255,255,0.03); }
.conv-item.active { background: rgba(124, 92, 252, 0.08); border: 1px solid rgba(124, 92, 252, 0.2); }
.conv-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #8888a0; }
.conv-meta { font-size: 0.6rem; color: #484860; flex-shrink: 0; }
.btn-del { background: none; border: none; color: #484860; cursor: pointer; font-size: 0.65rem; padding: 0; transition: color 0.15s; }
.btn-del:hover { color: #ef4444; }
.conv-empty { color: #484860; font-size: 0.72rem; text-align: center; padding: 1rem; }

.chat-main {
  flex: 1; display: flex; flex-direction: column; overflow: hidden;
}

.mode-toggle {
  display: flex; background: rgba(255,255,255,0.03); border-radius: 10px; overflow: hidden;
  border: 1px solid rgba(30, 30, 54, 0.4); flex-shrink: 0;
  padding: 2px;
}
.mode-option {
  padding: 0.25rem 0.65rem; font-size: 0.7rem; font-weight: 600;
  color: #484860; transition: all 0.2s; letter-spacing: 0.02em;
  border-radius: 7px; cursor: pointer;
}
.mode-option.active {
  background: linear-gradient(135deg, #7c5cfc, #6a4ae0);
  color: white; box-shadow: 0 2px 8px rgba(124, 92, 252, 0.25);
}
.mode-option:not(.active):hover { color: #8888a0; }

.agent-badge {
  font-size: 0.65rem; padding: 0.2rem 0.5rem; border-radius: 6px;
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
}
.agent-badge.active { background: rgba(74, 222, 128, 0.1); color: #4ade80; }
.agent-badge.disabled { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
.task-input {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(30, 30, 54, 0.4); border-radius: 8px;
  color: #8888a0; padding: 0.3rem 0.55rem; font-size: 0.7rem;
  width: 160px; outline: none; font-family: inherit;
  transition: all 0.2s;
}
.task-input:focus { border-color: rgba(124, 92, 252, 0.4); color: #e8e8f0; }
.task-input:disabled { opacity: 0.35; }
.task-input::placeholder { color: #383848; }
.btn-secondary {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(30, 30, 54, 0.4); color: #686880;
  padding: 0.35rem 0.7rem; border-radius: 8px; cursor: pointer; font-size: 0.72rem;
  transition: all 0.15s;
}
.btn-secondary:disabled { opacity: 0.25; cursor: default; }
.btn-secondary:hover:not(:disabled) { background: rgba(255,255,255,0.06); border-color: rgba(124, 92, 252, 0.2); color: #e8e8f0; }

.slider-group {
  display: flex; align-items: center; gap: 0.25rem;
  background: rgba(255,255,255,0.02); border-radius: 8px; padding: 0.2rem 0.4rem;
  border: 1px solid rgba(30, 30, 54, 0.4);
}
.slider-label { font-size: 0.6rem; color: #484860; text-transform: uppercase; letter-spacing: 0.03em; }
.slider { width: 56px; height: 4px; accent-color: #7c5cfc; cursor: pointer; }
.slider-value { font-size: 0.65rem; color: #686880; min-width: 26px; text-align: center; font-family: monospace; }

.copy-toast {
  position: absolute; right: 0.5rem; top: 0.5rem;
  background: rgba(74, 222, 128, 0.15); color: #4ade80; padding: 0.15rem 0.4rem;
  border-radius: 4px; font-size: 0.65rem; font-weight: 600;
  pointer-events: none;
}

.messages {
  flex: 1; overflow-y: auto; padding: 1.5rem 2rem;
  display: flex; flex-direction: column; gap: 0.75rem;
}
.message {
  display: flex; gap: 0.75rem; align-items: flex-start;
  animation: msgIn 0.25s ease-out;
}
@keyframes msgIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.message.user { flex-direction: row-reverse; }

.avatar {
  width: 30px; height: 30px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.75rem; font-weight: 700; flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(0,0,0,0.2);
}
.message.assistant .avatar {
  background: linear-gradient(135deg, #7c5cfc, #5a3cfc);
  color: white;
}
.message.user .avatar {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: white;
}

.bubble {
  max-width: 72%; padding: 0.7rem 1rem; border-radius: 14px;
  line-height: 1.55; font-size: 0.88rem;
  overflow-wrap: break-word; word-wrap: break-word; word-break: break-word;
}
.message.assistant .bubble {
  background: rgba(18, 18, 34, 0.7);
  border: 1px solid rgba(30, 30, 54, 0.5);
  backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
}
.message.user .bubble {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: white; border: none;
}

.content :deep(p) { margin: 0.4rem 0; }
.content :deep(p:first-child) { margin-top: 0; }
.content :deep(p:last-child) { margin-bottom: 0; }
.content :deep(code) { background: rgba(255,255,255,0.06); padding: 0.1rem 0.35rem; border-radius: 4px; font-size: 0.82rem; }
.content :deep(pre) {
  background: rgba(0,0,0,0.3); padding: 0.85rem 1rem; border-radius: 10px;
  overflow-x: auto; margin: 0.5rem 0; position: relative;
  border: 1px solid rgba(30, 30, 54, 0.4);
}
.content :deep(pre code) { background: none; padding: 0; color: #c0c0d0; }
.content :deep(ul), .content :deep(ol) { padding-left: 1.5rem; margin: 0.4rem 0; }

:deep(.tool-call) {
  display: inline-flex; align-items: center; gap: 0.3rem;
  background: rgba(124, 92, 252, 0.1); border: 1px solid rgba(124, 92, 252, 0.3);
  border-radius: 6px; padding: 0.1rem 0.45rem; margin: 0 0.1rem;
  font-size: 0.78rem; font-family: var(--mono, monospace);
  vertical-align: middle;
}
:deep(.tool-call-icon) { color: #7c5cfc; font-size: 0.65rem; }
:deep(.tool-call-name) { color: #c084fc; font-weight: 600; }
:deep(.tool-call-args) { color: #686880; }
:deep(.tool-result) {
  display: block; background: rgba(0,0,0,0.2); border: 1px solid rgba(30, 30, 54, 0.4);
  border-radius: 8px; padding: 0.4rem 0.6rem; margin: 0.35rem 0;
  font-size: 0.78rem; color: #8888a0; font-family: var(--mono, monospace);
  white-space: pre-wrap; word-break: break-all;
}

.tool-suggestions {
  display: flex; flex-direction: column; gap: 0.35rem; margin-top: 0.5rem;
  border-top: 1px solid rgba(30, 30, 54, 0.4); padding-top: 0.5rem;
}
.tool-suggestion-item {
  display: flex; align-items: center; gap: 0.35rem;
  background: rgba(0,0,0,0.2); border: 1px solid rgba(30, 30, 54, 0.4); border-radius: 8px;
  padding: 0.35rem 0.55rem; font-size: 0.78rem;
}
.tool-suggestion-icon { color: #7c5cfc; font-size: 0.7rem; }
.tool-suggestion-name { color: #c084fc; font-weight: 600; font-family: var(--mono, monospace); }
.tool-suggestion-desc { color: #585870; flex: 1; font-size: 0.72rem; }
.btn-run-tool {
  background: rgba(74, 222, 128, 0.1); border: none; color: #4ade80; padding: 0.2rem 0.55rem;
  border-radius: 6px; cursor: pointer; font-size: 0.65rem; font-weight: 600;
  transition: background 0.15s;
}
.btn-run-tool:hover:not(:disabled) { background: rgba(74, 222, 128, 0.2); }
.btn-run-tool:disabled { opacity: 0.35; cursor: default; }

.cursor { animation: blink 1.1s ease-in-out infinite; color: #7c5cfc; }
@keyframes blink { 50% { opacity: 0; } }

.empty-state {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 0.4rem; color: #484860;
}
.empty-icon { font-size: 2.5rem; color: #7c5cfc; opacity: 0.2; }
.empty-hint { font-size: 0.78rem; color: #383848; }
.startup-cmd {
  display: block; background: rgba(0,0,0,0.2); border: 1px solid rgba(30, 30, 54, 0.4);
  border-radius: 8px; padding: 0.35rem 0.7rem; font-size: 0.72rem;
  color: #686880; font-family: monospace; margin: 0.2rem 0;
}

.input-area {
  display: flex; gap: 0.5rem; padding: 0.85rem 1.25rem;
  border-top: 1px solid rgba(30, 30, 54, 0.4);
  background: rgba(8, 8, 18, 0.6);
  backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
}
textarea {
  flex: 1; background: rgba(255,255,255,0.03); border: 1px solid rgba(30, 30, 54, 0.5);
  border-radius: 10px; color: #e8e8f0; padding: 0.7rem 0.85rem;
  font-size: 0.85rem; resize: none; outline: none; font-family: inherit;
  max-height: 150px; transition: border-color 0.2s;
}
textarea:focus { border-color: rgba(124, 92, 252, 0.4); }
textarea:disabled { opacity: 0.35; }
textarea::placeholder { color: #383848; }

.btn-primary {
  background: linear-gradient(135deg, #7c5cfc, #6a4ae0);
  border: none; color: white; padding: 0.7rem 1.25rem;
  border-radius: 10px; cursor: pointer; font-weight: 600; font-size: 0.82rem;
  transition: all 0.15s; box-shadow: 0 2px 8px rgba(124, 92, 252, 0.2);
}
.btn-primary:disabled { opacity: 0.25; cursor: default; box-shadow: none; }
.btn-primary:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(124, 92, 252, 0.3); }

.btn-danger {
  background: #ef4444; border: none; color: white; padding: 0.7rem 1.25rem;
  border-radius: 10px; cursor: pointer; font-weight: 600; font-size: 0.82rem;
  transition: background 0.15s;
}
.btn-danger:hover { background: #dc2626; }
</style>
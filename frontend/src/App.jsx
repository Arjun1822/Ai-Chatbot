import { useEffect, useRef, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Prism from 'prismjs'
import 'prismjs/themes/prism-tomorrow.css'
import 'prismjs/components/prism-javascript'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-bash'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-markdown'
import 'prismjs/components/prism-css'
import 'prismjs/components/prism-sql'

import {
  Bot,
  Check,
  Clipboard,
  Edit2,
  FileCode,
  FileText,
  Menu,
  Moon,
  Paperclip,
  Plus,
  Send,
  Sparkles,
  Sun,
  Trash2,
  X,
  AlertTriangle,
  RefreshCw,
  Cpu,
} from 'lucide-react'

import {
  createConversation,
  deleteConversation,
  getConversation,
  getConversations,
  getHealth,
  streamMessage,
  updateConversation,
} from './services/api'

const suggestions = [
  'Explain quantum computing in simple terms',
  'Help me design a clean REST API structure',
  'Review this Python script for performance',
  'Draft a 7-day productivity roadmap',
]

function formatTime(value) {
  if (!value) return ''
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    }).format(new Date(value))
  } catch {
    return ''
  }
}

function CodeBlock({ inline, className, children, ...props }) {
  const match = /language-(\w+)/.exec(className || '')
  const language = match ? match[1] : ''
  const codeString = String(children).replace(/\n$/, '')
  const [copied, setCopied] = useState(false)

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(codeString)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      // fallback
    }
  }

  useEffect(() => {
    if (!inline && match) {
      Prism.highlightAll()
    }
  }, [codeString, inline, match])

  if (!inline && match) {
    return (
      <div className="code-block-wrapper">
        <div className="code-block-header">
          <span className="code-lang-tag">{language}</span>
          <button
            type="button"
            className="code-copy-btn"
            onClick={copyCode}
            aria-label="Copy code block"
          >
            {copied ? <Check size={13} /> : <Clipboard size={13} />}
            <span>{copied ? 'Copied!' : 'Copy code'}</span>
          </button>
        </div>
        <pre className={`language-${language}`}>
          <code className={`language-${language}`} {...props}>
            {codeString}
          </code>
        </pre>
      </div>
    )
  }

  return (
    <code className={`inline-code ${className || ''}`} {...props}>
      {children}
    </code>
  )
}

function SafeLink({ href, children, ...props }) {
  const isSafe = /^https?:\/\//i.test(href || '') || (href || '').startsWith('/')
  if (!isSafe) {
    return <span>{children}</span>
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
      {children}
    </a>
  )
}

function Message({ message }) {
  const [copied, setCopied] = useState(false)
  const isUser = message.role === 'user'

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      // fallback
    }
  }

  return (
    <article
      className={`message-row ${isUser ? 'user-row' : 'ai-row'}`}
      aria-label={`${isUser ? 'User' : 'Assistant'} message`}
    >
      <div className={`avatar ${isUser ? 'user-avatar' : 'ai-avatar'}`} aria-hidden="true">
        {isUser ? 'You' : <Bot size={17} />}
      </div>
      <div className="message-body">
        <div className="message-meta">
          <strong>{isUser ? 'You' : 'Orbit'}</strong>
          <span>{formatTime(message.created_at)}</span>
          {!isUser && message.meta?.latency_ms && (
            <span className="latency-tag">
              <Cpu size={11} /> {message.meta.latency_ms}ms
            </span>
          )}
        </div>
        <div className="message-content">
          {isUser ? (
            <div className="user-text-content">
              <p>{message.content}</p>
              {message.attachment_name && (
                <div className="message-attachment-pill">
                  <FileText size={13} />
                  <span>{message.attachment_name}</span>
                </div>
              )}
            </div>
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code: CodeBlock,
                a: SafeLink,
              }}
            >
              {message.content}
            </ReactMarkdown>
          )}
        </div>
        {!isUser && (
          <div className="message-actions">
            <button
              type="button"
              className="copy-button"
              onClick={copy}
              aria-label="Copy assistant response"
            >
              {copied ? <Check size={14} /> : <Clipboard size={14} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
        )}
      </div>
    </article>
  )
}

function App() {
  const [conversations, setConversations] = useState([])
  const [conversation, setConversation] = useState(null)
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [error, setError] = useState('')
  const [dark, setDark] = useState(() => localStorage.getItem('orbit-theme') === 'dark')
  const [search, setSearch] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Attachment state
  const [attachment, setAttachment] = useState(null)
  const fileInputRef = useRef(null)

  // Title editing state
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')

  // Delete confirmation state
  const [deleteConfirmId, setDeleteConfirmId] = useState(null)

  // System Health state
  const [healthStatus, setHealthStatus] = useState({
    online: false,
    database: 'connecting',
    llm: false,
    model: '',
  })

  const inputRef = useRef(null)
  const messagesRef = useRef(null)

  const checkHealth = useCallback(async () => {
    try {
      const res = await getHealth()
      if (res.data?.status === 'ok') {
        setHealthStatus({
          online: true,
          database: res.data.database,
          llm: res.data.llm_configured,
          model: res.data.model || 'Gemini',
        })
      }
    } catch {
      setHealthStatus((prev) => ({ ...prev, online: false }))
    }
  }, [])

  useEffect(() => {
    loadConversations()
    checkHealth()
    const interval = setInterval(checkHealth, 30000)
    return () => clearInterval(interval)
  }, [checkHealth])

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('orbit-theme', dark ? 'dark' : 'light')
  }, [dark])

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [conversation?.messages, streamingContent, loading])

  async function loadConversations() {
    try {
      const res = await getConversations()
      setConversations(res.data.conversations || [])
    } catch {
      setError('Could not connect to the backend. Please ensure the Flask server is running.')
    }
  }

  async function newChat() {
    try {
      const res = await createConversation('New conversation')
      const created = res.data.conversation
      setConversation(created)
      setConversations((items) => [created, ...items])
      setSidebarOpen(false)
      setAttachment(null)
      setDraft('')
      inputRef.current?.focus()
    } catch {
      setError('Could not initialize a new conversation.')
    }
  }

  async function openChat(id) {
    if (conversation?._id === id) return
    try {
      const res = await getConversation(id)
      setConversation(res.data.conversation)
      setSidebarOpen(false)
      setAttachment(null)
      setError('')
    } catch {
      setError('Could not retrieve conversation.')
    }
  }

  async function confirmRemoveChat(id) {
    try {
      await deleteConversation(id)
      setConversations((items) => items.filter((item) => item._id !== id))
      if (conversation?._id === id) {
        setConversation(null)
      }
      setDeleteConfirmId(null)
    } catch {
      setError('Failed to delete the conversation.')
    }
  }

  async function handleSaveTitle(id, e) {
    e?.preventDefault()
    if (!editTitle.trim()) {
      setEditingId(null)
      return
    }
    try {
      const res = await updateConversation(id, editTitle.trim())
      const updated = res.data.conversation
      setConversations((items) =>
        items.map((item) => (item._id === id ? { ...item, title: updated.title } : item))
      )
      if (conversation?._id === id) {
        setConversation((prev) => (prev ? { ...prev, title: updated.title } : prev))
      }
      setEditingId(null)
    } catch {
      setError('Failed to update conversation title.')
    }
  }

  function handleFileSelect(e) {
    const file = e.target.files?.[0]
    if (!file) return

    // 100 KB limit for safe text attachments
    if (file.size > 100 * 1024) {
      setError('File exceeds maximum allowed size (100 KB).')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    const reader = new FileReader()
    reader.onload = (event) => {
      setAttachment({
        name: file.name,
        size: Math.round(file.size / 1024),
        content: event.target?.result || '',
      })
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
    reader.onerror = () => {
      setError('Failed to read the selected file.')
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
    reader.readAsText(file)
  }

  async function submit(event) {
    event?.preventDefault()
    if ((!draft.trim() && !attachment) || loading) return

    const messageText = draft.trim()
    const activeAttachment = attachment

    setDraft('')
    setAttachment(null)
    setError('')
    setLoading(true)
    setStreamingContent('')

    // Create optimistic user message
    const tempUserMsg = {
      role: 'user',
      content: activeAttachment
        ? `${messageText}\n\n[Attached File: ${activeAttachment.name}]\n\`\`\`\n${activeAttachment.content}\n\`\`\``
        : messageText,
      attachment_name: activeAttachment?.name,
      created_at: new Date().toISOString(),
    }

    // Add optimistic user message to conversation
    setConversation((prev) => ({
      _id: prev?._id || 'temp',
      title: prev?.title || messageText.slice(0, 48) || 'New conversation',
      messages: [...(prev?.messages || []), tempUserMsg],
    }))

    let accumulatedText = ''

    await streamMessage(conversation?._id, messageText, activeAttachment, {
      onChunk: (chunk) => {
        accumulatedText += chunk
        setStreamingContent(accumulatedText)
      },
      onDone: (data) => {
        setLoading(false)
        setStreamingContent('')
        if (data.conversation) {
          setConversation(data.conversation)
          setConversations((items) => [
            data.conversation,
            ...items.filter((i) => i._id !== data.conversation._id),
          ])
        }
        inputRef.current?.focus()
      },
      onError: (err) => {
        setLoading(false)
        setStreamingContent('')
        setDraft(messageText)
        if (activeAttachment) setAttachment(activeAttachment)
        setError(err.message || 'Something went wrong. Please try again.')
        inputRef.current?.focus()
      },
    })
  }

  const visibleConversations = conversations.filter((item) =>
    (item?.title || '').toLowerCase().includes(search.toLowerCase())
  )

  const hasMessages = (conversation?.messages?.length || 0) > 0 || streamingContent

  return (
    <div className="app-shell">
      {/* Mobile Sidebar Overlay */}
      {sidebarOpen && (
        <button
          type="button"
          className="overlay"
          onClick={() => setSidebarOpen(false)}
          aria-label="Close sidebar"
        />
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirmId && (
        <div className="modal-backdrop">
          <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
            <div className="dialog-icon-wrap">
              <AlertTriangle size={24} className="dialog-warn-icon" />
            </div>
            <h3 id="dialog-title">Delete Conversation?</h3>
            <p>This action cannot be undone. All messages in this conversation will be permanently removed.</p>
            <div className="dialog-actions">
              <button
                type="button"
                className="btn-cancel"
                onClick={() => setDeleteConfirmId(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-danger"
                onClick={() => confirmRemoveChat(deleteConfirmId)}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? 'is-open' : ''}`} aria-label="Conversation history">
        <div className="sidebar-head">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              <Sparkles size={17} />
            </span>
            <span>
              Orbit<span className="brand-dot">.</span>
            </span>
          </div>
          <button
            type="button"
            className="icon-button mobile-only"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close sidebar"
          >
            <X size={19} />
          </button>
        </div>

        <button
          type="button"
          className="new-chat"
          onClick={newChat}
          aria-label="Start new conversation"
        >
          <Plus size={18} /> New chat
        </button>

        <div className="history-label">Your conversations</div>
        <input
          className="search-input"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search chats..."
          aria-label="Search conversation history"
        />

        <div className="history-list" role="navigation" aria-label="Conversations">
          {visibleConversations.map((item) => (
            <div
              key={item._id}
              className={`history-item-wrap ${conversation?._id === item._id ? 'active' : ''}`}
            >
              {editingId === item._id ? (
                <form
                  className="rename-form"
                  onSubmit={(e) => handleSaveTitle(item._id, e)}
                >
                  <input
                    type="text"
                    className="rename-input"
                    value={editTitle}
                    autoFocus
                    onChange={(e) => setEditTitle(e.target.value)}
                    onBlur={(e) => handleSaveTitle(item._id, e)}
                    onKeyDown={(e) => {
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                  />
                </form>
              ) : (
                <button
                  type="button"
                  className={`history-item ${conversation?._id === item._id ? 'active' : ''}`}
                  onClick={() => openChat(item._id)}
                  title={item.title}
                >
                  <span>{item.title || 'Untitled conversation'}</span>
                </button>
              )}

              <div className="history-item-actions">
                <button
                  type="button"
                  className="action-icon-btn"
                  title="Rename title"
                  aria-label="Rename conversation"
                  onClick={(e) => {
                    e.stopPropagation()
                    setEditingId(item._id)
                    setEditTitle(item.title || '')
                  }}
                >
                  <Edit2 size={13} />
                </button>
                <button
                  type="button"
                  className="action-icon-btn danger"
                  title="Delete chat"
                  aria-label="Delete conversation"
                  onClick={(e) => {
                    e.stopPropagation()
                    setDeleteConfirmId(item._id)
                  }}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}

          {!visibleConversations.length && (
            <p className="empty-history">
              {search ? 'No matching conversations' : 'No conversations yet'}
            </p>
          )}
        </div>

        <div className="sidebar-foot" title={`Backend: ${healthStatus.online ? 'Online' : 'Offline'} | DB: ${healthStatus.database} | LLM: ${healthStatus.llm ? 'Configured' : 'Missing Key'}`}>
          <span
            className={`status-dot ${
              !healthStatus.online
                ? 'offline'
                : healthStatus.database === 'connected'
                ? 'connected'
                : 'in-memory'
            }`}
            aria-hidden="true"
          />
          <div className="status-meta">
            <span className="status-title">
              {healthStatus.online
                ? healthStatus.database === 'connected'
                  ? 'Cloud Database'
                  : 'Local Storage'
                : 'Disconnected'}
            </span>
            <span className="status-sub">
              {healthStatus.online
                ? `${healthStatus.model || 'Gemini'} • Ready`
                : 'Check Flask Backend'}
            </span>
          </div>
        </div>
      </aside>

      {/* Main Panel */}
      <main className="main-panel">
        <header className="topbar">
          <div className="topbar-left">
            <button
              type="button"
              className="icon-button mobile-only"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open sidebar"
            >
              <Menu size={20} />
            </button>
            <div className="topbar-title">
              <span className="eyebrow">AI ASSISTANT</span>
              <h1>{conversation?.title || 'A quiet place to think'}</h1>
            </div>
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={() => setDark(!dark)}
            aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            title={dark ? 'Use light theme' : 'Use dark theme'}
          >
            {dark ? <Sun size={19} /> : <Moon size={19} />}
          </button>
        </header>

        {/* Conversation Area */}
        <section className="conversation" ref={messagesRef} tabIndex={0} aria-label="Chat messages">
          {!hasMessages ? (
            <div className="welcome">
              <div className="welcome-icon" aria-hidden="true">
                <Sparkles size={24} />
              </div>
              <p className="eyebrow">GOOD TO SEE YOU</p>
              <h2>
                What are we exploring
                <br />
                today?
              </h2>
              <p className="welcome-copy">
                Ask anything. Orbit keeps the thread in view
                <br className="desktop-only" /> so your thinking can go further.
              </p>
              <div className="suggestions" role="group" aria-label="Suggested prompts">
                {suggestions.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => {
                      setDraft(item)
                      inputRef.current?.focus()
                    }}
                  >
                    <span>{item}</span>
                    <span className="arrow" aria-hidden="true">↗</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {conversation?.messages?.map((message, index) => (
                <Message message={message} key={`${message.role}-${index}`} />
              ))}

              {/* Streaming AI Chunk Output */}
              {streamingContent && (
                <article className="message-row ai-row" aria-label="Assistant streaming response">
                  <div className="avatar ai-avatar" aria-hidden="true">
                    <Bot size={17} />
                  </div>
                  <div className="message-body">
                    <div className="message-meta">
                      <strong>Orbit</strong>
                      <span>generating...</span>
                    </div>
                    <div className="message-content">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          code: CodeBlock,
                          a: SafeLink,
                        }}
                      >
                        {streamingContent}
                      </ReactMarkdown>
                    </div>
                  </div>
                </article>
              )}

              {/* Typing indicator when waiting for stream start */}
              {loading && !streamingContent && (
                <div className="message-row ai-row" aria-live="polite">
                  <div className="avatar ai-avatar" aria-hidden="true">
                    <Bot size={17} />
                  </div>
                  <div className="message-body">
                    <div className="message-meta">
                      <strong>Orbit</strong>
                      <span>thinking</span>
                    </div>
                    <div className="typing" aria-label="Thinking indicator">
                      <i />
                      <i />
                      <i />
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button
                type="button"
                onClick={() => setError('')}
                aria-label="Dismiss error message"
              >
                <X size={15} />
              </button>
            </div>
          )}
        </section>

        {/* Input Composer */}
        <div className="composer-wrap">
          {/* File Attachment Pill */}
          {attachment && (
            <div className="attachment-chip">
              <FileCode size={14} className="att-icon" />
              <span className="att-name">{attachment.name}</span>
              <span className="att-size">({attachment.size} KB)</span>
              <button
                type="button"
                className="att-remove"
                onClick={() => setAttachment(null)}
                aria-label="Remove attached file"
              >
                <X size={13} />
              </button>
            </div>
          )}

          <form className="composer" onSubmit={submit}>
            {/* Hidden File Input */}
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              accept=".txt,.md,.py,.js,.jsx,.ts,.tsx,.json,.csv,.sql,.html,.css,.yaml,.yml"
              style={{ display: 'none' }}
              aria-label="Attach code or text file"
            />

            <button
              type="button"
              className="attach-button"
              onClick={() => fileInputRef.current?.click()}
              title="Attach text or code file (up to 100 KB)"
              aria-label="Attach file"
            >
              <Paperclip size={18} />
            </button>

            <textarea
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  submit(event)
                }
              }}
              placeholder="Message Orbit... (Enter to send, Shift+Enter for new line)"
              rows={1}
              aria-label="Chat input message"
            />

            <button
              type="submit"
              className="send-button"
              disabled={(!draft.trim() && !attachment) || loading}
              aria-label="Send message"
            >
              {loading ? <RefreshCw size={17} className="spin-icon" /> : <Send size={18} />}
            </button>
          </form>

          <p className="composer-hint">Orbit can make mistakes. Verify important information.</p>
        </div>
      </main>
    </div>
  )
}

export default App

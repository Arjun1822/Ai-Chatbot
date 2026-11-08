import axios from 'axios'

// Resolve backend API URL (supports with or without trailing /api)
const rawApiUrl = (process.env.REACT_APP_API_URL || 'http://localhost:5000').trim()
const cleanUrl = rawApiUrl.replace(/\/+$/, '')
const BASE_URL = cleanUrl.endsWith('/api') ? cleanUrl : `${cleanUrl}/api`

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Attach authorization token if present in localStorage
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('orbit_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// System & Health
export const getHealth = () => api.get('/health')
export const getMetrics = () => api.get('/admin/metrics')

// Authentication
export const registerUser = (email, password, name) =>
  api.post('/auth/register', { email, password, name })
export const loginUser = (email, password) =>
  api.post('/auth/login', { email, password })
export const getMe = () => api.get('/auth/me')
export const logoutUser = () => {
  localStorage.removeItem('orbit_token')
  return api.post('/auth/logout')
}

// Conversations
export const getConversations = () => api.get('/conversations')
export const getConversation = (id) => api.get(`/conversations/${id}`)
export const createConversation = (title = 'New conversation') =>
  api.post('/conversations', { title })
export const updateConversation = (id, title) =>
  api.patch(`/conversations/${id}`, { title })
export const deleteConversation = (id) => api.delete(`/conversations/${id}`)

// Chat
export const sendMessage = (conversationId, message, attachment = null, mode = 'chat') =>
  api.post('/chat', { conversation_id: conversationId, message, attachment, mode })

// RAG Documents
export const listDocuments = () => api.get('/documents')
export const uploadDocument = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/documents', formData)
}
export const deleteDocument = (id) => api.delete(`/documents/${id}`)

// Persistent Memory
export const listMemories = (category) =>
  api.get('/memories', { params: category ? { category } : {} })
export const createMemory = (content, category = 'fact', importance = 3) =>
  api.post('/memories', { content, category, importance })
export const updateMemory = (id, data) => api.patch(`/memories/${id}`, data)
export const deleteMemory = (id) => api.delete(`/memories/${id}`)

// Streaming Chat with Agent & Document modes
export async function streamMessage(
  conversationId,
  message,
  attachment,
  { onChunk, onDone, onError, onToolCall, onToolResult },
  mode = 'chat'
) {
  try {
    const headers = { 'Content-Type': 'application/json' }
    const token = localStorage.getItem('orbit_token')
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }

    const response = await fetch(`${BASE_URL}/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        conversation_id: conversationId,
        message,
        attachment,
        mode,
      }),
    })

    if (!response.ok) {
      let errMsg = 'Failed to generate response'
      try {
        const errJson = await response.json()
        errMsg = errJson.error || errMsg
      } catch {
        errMsg = `Server returned status ${response.status}`
      }
      onError(new Error(errMsg))
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (trimmed.startsWith('data: ')) {
          try {
            const data = JSON.parse(trimmed.slice(6))
            if (data.type === 'chunk') {
              onChunk(data.text || data.content || '')
            } else if (data.type === 'tool_call') {
              if (onToolCall) onToolCall(data)
            } else if (data.type === 'tool_result') {
              if (onToolResult) onToolResult(data)
            } else if (data.type === 'done') {
              onDone(data)
            } else if (data.type === 'error') {
              onError(new Error(data.error || data.message || 'Stream error'))
            }
          } catch {
            // ignore non-json line
          }
        }
      }
    }
  } catch (err) {
    onError(err)
  }
}

export default api

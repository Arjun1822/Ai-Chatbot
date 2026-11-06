import axios from 'axios'

const BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000/api'

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
})

export const getHealth = () => api.get('/health')
export const getConversations = () => api.get('/conversations')
export const getConversation = (id) => api.get(`/conversations/${id}`)
export const createConversation = (title = 'New conversation') => api.post('/conversations', { title })
export const updateConversation = (id, title) => api.patch(`/conversations/${id}`, { title })
export const deleteConversation = (id) => api.delete(`/conversations/${id}`)
export const sendMessage = (conversationId, message, attachment = null) =>
  api.post('/chat', { conversation_id: conversationId, message, attachment })

export async function streamMessage(conversationId, message, attachment, { onChunk, onDone, onError }) {
  try {
    const response = await fetch(`${BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        conversation_id: conversationId,
        message,
        attachment,
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
              onChunk(data.text)
            } else if (data.type === 'done') {
              onDone(data)
            } else if (data.type === 'error') {
              onError(new Error(data.error))
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

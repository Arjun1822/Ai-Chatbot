import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from '../App'
import * as api from '../services/api'

// Mock api service
jest.mock('../services/api', () => ({
  getHealth: jest.fn(),
  getConversations: jest.fn(),
  getConversation: jest.fn(),
  createConversation: jest.fn(),
  updateConversation: jest.fn(),
  deleteConversation: jest.fn(),
  streamMessage: jest.fn(),
}))

describe('Orbit AI Frontend Tests', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    localStorage.clear()

    // Default mock implementations
    api.getHealth.mockResolvedValue({
      data: {
        status: 'ok',
        database: 'connected',
        llm_configured: true,
        model: 'gemini-3.5-flash-lite',
      },
    })

    api.getConversations.mockResolvedValue({
      data: {
        conversations: [
          {
            _id: 'conv-1',
            title: 'First Chat',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
          {
            _id: 'conv-2',
            title: 'Second Chat',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
      },
    })
  })

  test('renders Orbit branding and empty state welcome screen', async () => {
    render(<App />)

    // Wait for conversations to load asynchronously
    await waitFor(() => {
      expect(screen.getByText('First Chat')).toBeInTheDocument()
    })

    expect(screen.getAllByText(/Orbit/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/GOOD TO SEE YOU/i)).toBeInTheDocument()
    expect(screen.getByText(/What are we exploring/i)).toBeInTheDocument()
    expect(screen.getByText('Second Chat')).toBeInTheDocument()
  })

  test('clicking a suggestion chip populates composer textarea', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('First Chat')).toBeInTheDocument()
    })

    const suggestion = screen.getByText('Explain quantum computing in simple terms')
    fireEvent.click(suggestion)

    const textarea = screen.getByPlaceholderText(/Message Orbit\.\.\./i)
    expect(textarea.value).toBe('Explain quantum computing in simple terms')
  })

  test('conversation search filters conversation list safely', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('First Chat')).toBeInTheDocument()
      expect(screen.getByText('Second Chat')).toBeInTheDocument()
    })

    const searchInput = screen.getByPlaceholderText(/Search chats\.\.\./i)
    fireEvent.change(searchInput, { target: { value: 'Second' } })

    expect(screen.queryByText('First Chat')).not.toBeInTheDocument()
    expect(screen.getByText('Second Chat')).toBeInTheDocument()
  })

  test('toggling dark theme changes dataset and persists to localStorage', async () => {
    render(<App />)

    const themeBtn = screen.getByTitle(/Use dark theme/i)
    fireEvent.click(themeBtn)

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('orbit-theme')).toBe('dark')

    const lightThemeBtn = screen.getByTitle(/Use light theme/i)
    fireEvent.click(lightThemeBtn)

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('orbit-theme')).toBe('light')
  })

  test('opening a conversation loads messages', async () => {
    api.getConversation.mockResolvedValueOnce({
      data: {
        conversation: {
          _id: 'conv-1',
          title: 'First Chat',
          messages: [
            {
              role: 'user',
              content: 'What is Python?',
              created_at: new Date().toISOString(),
            },
            {
              role: 'assistant',
              content: 'Python is a high-level language.',
              created_at: new Date().toISOString(),
              meta: { latency_ms: 120 },
            },
          ],
        },
      },
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('First Chat')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('First Chat'))

    await waitFor(() => {
      expect(screen.getByText('What is Python?')).toBeInTheDocument()
      expect(screen.getByText('Python is a high-level language.')).toBeInTheDocument()
    })
  })

  test('delete confirmation modal appears when delete button is clicked', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('First Chat')).toBeInTheDocument()
    })

    const deleteBtns = screen.getAllByLabelText(/Delete conversation/i)
    fireEvent.click(deleteBtns[0])

    expect(screen.getByText(/Delete Conversation\?/i)).toBeInTheDocument()
    expect(screen.getByText(/This action cannot be undone\./i)).toBeInTheDocument()

    // Clicking cancel closes the modal
    const cancelBtn = screen.getByText('Cancel')
    fireEvent.click(cancelBtn)

    expect(screen.queryByText(/Delete Conversation\?/i)).not.toBeInTheDocument()
  })
})

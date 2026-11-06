import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from '../App'
import * as api from '../services/api'

jest.mock('../services/api', () => ({
  getHealth: jest.fn(),
  getConversations: jest.fn(),
  getConversation: jest.fn(),
  createConversation: jest.fn(),
  updateConversation: jest.fn(),
  deleteConversation: jest.fn(),
  streamMessage: jest.fn(),
}))

describe('Advanced Frontend QA Tests', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    localStorage.clear()

    api.getHealth.mockResolvedValue({
      data: { status: 'ok', database: 'connected', llm_configured: true, model: 'gemini-3.5-flash-lite' },
    })
    api.getConversations.mockResolvedValue({
      data: { conversations: [{ _id: 'c1', title: 'Active Chat', created_at: new Date().toISOString() }] },
    })
  })

  test('TC-FRONT-01: Duplicate message prevention and button disabling while loading', async () => {
    render(<App />)
    await waitFor(() => expect(screen.getByText('Active Chat')).toBeInTheDocument())

    const input = screen.getByPlaceholderText(/Message Orbit\.\.\./i)
    const sendButton = screen.getByLabelText('Send message')

    fireEvent.change(input, { target: { value: 'First message' } })
    expect(sendButton).not.toBeDisabled()

    // Mock streamMessage to hang in flight
    let completeStream
    api.streamMessage.mockImplementation((id, msg, att, callbacks) => {
      return new Promise((resolve) => {
        completeStream = () => {
          callbacks.onDone({ conversation: { _id: 'c1', title: 'Active Chat', messages: [] } })
          resolve()
        }
      })
    })

    // Submit message
    fireEvent.click(sendButton)

    // Button must now be disabled to prevent duplicate submissions
    expect(sendButton).toBeDisabled()
    expect(api.streamMessage).toHaveBeenCalledTimes(1)

    // Attempt second submission while loading
    fireEvent.click(sendButton)
    expect(api.streamMessage).toHaveBeenCalledTimes(1) // Still 1

    // Finish stream
    completeStream()
  })

  test('TC-FRONT-02: Empty or whitespace-only messages are blocked', async () => {
    render(<App />)
    await waitFor(() => expect(screen.getByText('Active Chat')).toBeInTheDocument())

    const input = screen.getByPlaceholderText(/Message Orbit\.\.\./i)
    const sendButton = screen.getByLabelText('Send message')

    // Empty
    fireEvent.change(input, { target: { value: '' } })
    expect(sendButton).toBeDisabled()
    fireEvent.click(sendButton)
    expect(api.streamMessage).not.toHaveBeenCalled()

    // Spaces only
    fireEvent.change(input, { target: { value: '    \n   ' } })
    expect(sendButton).toBeDisabled()
    fireEvent.click(sendButton)
    expect(api.streamMessage).not.toHaveBeenCalled()
  })

  test('TC-FRONT-03: Malicious script tags in user messages are not executed as raw HTML', async () => {
    api.getConversation.mockResolvedValueOnce({
      data: {
        conversation: {
          _id: 'c1',
          title: 'Active Chat',
          messages: [
            {
              role: 'user',
              content: '<script>window.xss=1</script><img src=x onerror=window.xss=2>',
              created_at: new Date().toISOString(),
            },
          ],
        },
      },
    })

    render(<App />)
    await waitFor(() => expect(screen.getByText('Active Chat')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Active Chat'))

    await waitFor(() => {
      // Must be rendered as literal text content, not raw executable DOM
      expect(screen.getByText(/<script>window\.xss=1<\/script>/i)).toBeInTheDocument()
      expect(window.xss).toBeUndefined()
    })
  })

  test('TC-FRONT-04: Network disconnection triggers error banner with dismiss control', async () => {
    api.streamMessage.mockImplementation((id, msg, att, callbacks) => {
      callbacks.onError(new Error('Network error: Failed to connect to server'))
      return Promise.resolve()
    })

    render(<App />)
    await waitFor(() => expect(screen.getByText('Active Chat')).toBeInTheDocument())

    const input = screen.getByPlaceholderText(/Message Orbit\.\.\./i)
    fireEvent.change(input, { target: { value: 'Trigger network fail' } })
    fireEvent.click(screen.getByLabelText('Send message'))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
      expect(screen.getByText(/Network error: Failed to connect to server/i)).toBeInTheDocument()
    })

    // Dismiss error banner
    fireEvent.click(screen.getByLabelText('Dismiss error message'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  test('TC-FRONT-05: Deleting the currently active conversation returns user to welcome view', async () => {
    api.getConversation.mockResolvedValueOnce({
      data: {
        conversation: {
          _id: 'c1',
          title: 'Active Chat',
          messages: [{ role: 'user', content: 'Hello active' }],
        },
      },
    })
    api.deleteConversation.mockResolvedValueOnce({ data: { message: 'Deleted' } })

    render(<App />)
    await waitFor(() => expect(screen.getByText('Active Chat')).toBeInTheDocument())

    // Open chat
    fireEvent.click(screen.getByText('Active Chat'))
    await waitFor(() => expect(screen.getByText('Hello active')).toBeInTheDocument())

    // Click delete
    fireEvent.click(screen.getByLabelText('Delete conversation'))
    expect(screen.getByText('Delete Conversation?')).toBeInTheDocument()

    // Confirm delete
    fireEvent.click(screen.getByText('Delete'))

    // Active conversation cleared, welcome screen restored
    await waitFor(() => {
      expect(screen.queryByText('Hello active')).not.toBeInTheDocument()
      expect(screen.getByText('GOOD TO SEE YOU')).toBeInTheDocument()
    })
  })
})


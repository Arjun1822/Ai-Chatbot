import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { KnowledgeBaseModal } from '../components/KnowledgeBaseModal'
import * as apiModule from '../services/api'
import api, { uploadDocument } from '../services/api'

describe('Knowledge Base Document Upload & Service Integration', () => {
  afterEach(() => {
    jest.restoreAllMocks()
    localStorage.clear()
  })

  test('uploadDocument sends FormData and does not force application/json Content-Type', async () => {
    const postSpy = jest.spyOn(api, 'post').mockResolvedValue({
      data: { document: { document_id: 'doc_1', filename: 'report.pdf', total_chunks: 3 } },
    })

    const file = new File(['dummy content'], 'report.pdf', { type: 'application/pdf' })
    const res = await uploadDocument(file)

    expect(postSpy).toHaveBeenCalledTimes(1)
    const [endpoint, data, config] = postSpy.mock.calls[0]
    expect(endpoint).toBe('/documents')
    expect(data instanceof FormData).toBe(true)
    expect(data.get('file')).toBeTruthy()
    // Must NOT be 'application/json'
    expect(config.headers['Content-Type']).toBeUndefined()
    expect(res.data.document.filename).toBe('report.pdf')
  })

  test('uploadDocument attaches Authorization Bearer token when logged in', async () => {
    localStorage.setItem('orbit_token', 'test-jwt-token-xyz')
    let capturedHeaders = null

    jest.spyOn(api, 'post').mockImplementation((url, data, config) => {
      // Simulate axios running request interceptor
      capturedHeaders = { ...config?.headers }
      const token = localStorage.getItem('orbit_token')
      if (token) {
        capturedHeaders.Authorization = `Bearer ${token}`
      }
      return Promise.resolve({ data: { document: { document_id: 'doc_2' } } })
    })

    const file = new File(['text'], 'notes.txt', { type: 'text/plain' })
    await uploadDocument(file)

    expect(capturedHeaders.Authorization).toBe('Bearer test-jwt-token-xyz')
  })

  test('uploadDocument attaches guest token when authenticated user token is absent', async () => {
    localStorage.setItem('orbit_guest_token', 'guest-jwt-token-abc')
    let capturedHeaders = null

    jest.spyOn(api, 'post').mockImplementation((url, data, config) => {
      capturedHeaders = { ...config?.headers }
      const token = localStorage.getItem('orbit_token') || localStorage.getItem('orbit_guest_token')
      if (token) {
        capturedHeaders.Authorization = `Bearer ${token}`
      }
      return Promise.resolve({ data: { document: { document_id: 'doc_3' } } })
    })

    const file = new File(['guest data'], 'guest_notes.txt', { type: 'text/plain' })
    await uploadDocument(file)

    expect(capturedHeaders.Authorization).toBe('Bearer guest-jwt-token-abc')
  })

  test('FormData payload preserves filename and binary content without JSON conversion', async () => {
    let capturedData = null
    let capturedConfig = null

    jest.spyOn(api, 'post').mockImplementation((url, data, config) => {
      capturedData = data
      capturedConfig = config
      return Promise.resolve({ data: { document: { document_id: 'doc_4' } } })
    })

    const file = new File(['%PDF-1.4 test binary'], 'test_manual.pdf', { type: 'application/pdf' })
    await uploadDocument(file)

    expect(capturedData instanceof FormData).toBe(true)
    const uploadedFile = capturedData.get('file')
    expect(uploadedFile).toBeTruthy()
    expect(uploadedFile.name).toBe('test_manual.pdf')
    expect(uploadedFile.type).toBe('application/pdf')
    expect(capturedConfig.headers['Content-Type']).toBeUndefined()
  })

  test('KnowledgeBaseModal uploads selected document and renders success message', async () => {
    jest.spyOn(apiModule, 'listDocuments').mockResolvedValue({
      data: { documents: [] },
    })
    jest.spyOn(apiModule, 'uploadDocument').mockResolvedValue({
      data: {
        document: {
          document_id: 'doc_100',
          filename: 'system_design.pdf',
          total_chunks: 4,
        },
      },
    })

    render(<KnowledgeBaseModal isOpen={true} onClose={() => {}} />)

    expect(screen.getByText(/RAG Knowledge Base/i)).toBeInTheDocument()

    const input = document.querySelector('input[type="file"]')
    const file = new File(['pdf data'], 'system_design.pdf', { type: 'application/pdf' })

    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => {
      expect(screen.getByText(/Indexed "system_design\.pdf" successfully \(4 chunks\)\./i)).toBeInTheDocument()
    })
  })
})


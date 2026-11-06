import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { ToolActivityCard } from '../components/ToolActivityCard'
import { CitationPill } from '../components/CitationPill'
import { MetricsModal } from '../components/MetricsModal'

describe('Agent Platform Components', () => {
  test('ToolActivityCard renders tool name, execution time, and toggles details', () => {
    const toolCall = {
      id: 'call_1',
      tool_name: 'calculator',
      arguments: { expression: '25 * 4' },
    }
    const toolResult = {
      tool_name: 'calculator',
      success: true,
      output: { result: 100, formatted: '100' },
      execution_time_ms: 12,
    }

    render(<ToolActivityCard toolCall={toolCall} toolResult={toolResult} />)

    expect(screen.getByText(/Tool: calculator/i)).toBeInTheDocument()
    expect(screen.getByText(/12ms/i)).toBeInTheDocument()
    expect(screen.getByText(/success/i)).toBeInTheDocument()

    // Toggle details
    const headerBtn = screen.getByRole('button')
    fireEvent.click(headerBtn)

    expect(screen.getByText(/Input Arguments:/i)).toBeInTheDocument()
    expect(screen.getByText(/Output Observation:/i)).toBeInTheDocument()
  })

  test('CitationPill renders filename and opens dialog on click', () => {
    const citation = {
      source_number: 1,
      document_id: 'doc_123',
      filename: 'architecture.pdf',
      score: 0.92,
      snippet: 'This section defines the multi-tenant architecture and security constraints.',
    }

    render(<CitationPill citation={citation} index={0} />)

    const pillBtn = screen.getByText(/Source \[1\]: architecture\.pdf/i)
    expect(pillBtn).toBeInTheDocument()
    expect(screen.getByText(/92% match/i)).toBeInTheDocument()

    // Click to open citation dialog
    fireEvent.click(pillBtn)

    expect(screen.getByText(/Extracted Text Chunk:/i)).toBeInTheDocument()
    expect(screen.getByText(/multi-tenant architecture and security constraints/i)).toBeInTheDocument()
  })

  test('MetricsModal renders platform metrics and tool badges when open', () => {
    render(<MetricsModal isOpen={true} onClose={() => {}} />)

    expect(screen.getByText(/Platform Observability/i)).toBeInTheDocument()
    expect(screen.getByText(/Conversations/i)).toBeInTheDocument()
    expect(screen.getByText(/Knowledge Docs/i)).toBeInTheDocument()
    expect(screen.getByText(/calculator/i)).toBeInTheDocument()
  })
})

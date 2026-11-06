import React, { useState } from 'react'
import { ChevronDown, ChevronRight, Wrench, CheckCircle, AlertCircle, Clock } from 'lucide-react'

export function ToolActivityCard({ toolCall, toolResult }) {
  const [expanded, setExpanded] = useState(false)
  const isPending = !toolResult
  const isSuccess = toolResult?.success

  return (
    <div className={`tool-activity-card ${isPending ? 'pending' : isSuccess ? 'success' : 'failed'}`}>
      <button
        type="button"
        className="tool-activity-header"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <div className="tool-header-left">
          <Wrench size={14} className="tool-icon" />
          <span className="tool-name">Tool: {toolCall?.tool_name || toolResult?.tool_name}</span>
          {isPending ? (
            <span className="tool-badge pending">executing...</span>
          ) : isSuccess ? (
            <span className="tool-badge success">
              <CheckCircle size={11} /> success
            </span>
          ) : (
            <span className="tool-badge failed">
              <AlertCircle size={11} /> failed
            </span>
          )}
        </div>
        <div className="tool-header-right">
          {toolResult?.execution_time_ms !== undefined && (
            <span className="tool-time">
              <Clock size={11} /> {toolResult.execution_time_ms}ms
            </span>
          )}
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </button>

      {expanded && (
        <div className="tool-activity-body">
          <div className="tool-section">
            <span className="tool-section-label">Input Arguments:</span>
            <pre className="tool-code-preview">
              {JSON.stringify(toolCall?.arguments || {}, null, 2)}
            </pre>
          </div>
          {toolResult && (
            <div className="tool-section">
              <span className="tool-section-label">Output Observation:</span>
              <pre className="tool-code-preview">
                {typeof toolResult.output === 'object'
                  ? JSON.stringify(toolResult.output, null, 2)
                  : String(toolResult.output || toolResult.error)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default ToolActivityCard

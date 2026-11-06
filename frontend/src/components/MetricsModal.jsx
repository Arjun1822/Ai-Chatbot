import React, { useState, useEffect } from 'react'
import { Activity, X, RefreshCw, Database, Server, Wrench, FileText, MessageSquare } from 'lucide-react'
import { getMetrics } from '../services/api'

export function MetricsModal({ isOpen, onClose }) {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (isOpen) {
      loadMetrics()
    }
  }, [isOpen])

  const loadMetrics = async () => {
    setLoading(true)
    try {
      const res = await getMetrics()
      setMetrics(res.data.metrics)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="metrics-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-wrap">
            <Activity size={18} />
            <h3>Platform Observability</h3>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <div className="metrics-grid">
            <div className="metric-card">
              <div className="metric-header">
                <MessageSquare size={16} />
                <span>Conversations</span>
              </div>
              <div className="metric-value">{metrics?.conversations_count ?? 0}</div>
            </div>

            <div className="metric-card">
              <div className="metric-header">
                <FileText size={16} />
                <span>Knowledge Docs</span>
              </div>
              <div className="metric-value">{metrics?.documents_count ?? 0}</div>
            </div>

            <div className="metric-card">
              <div className="metric-header">
                <Database size={16} />
                <span>Database Mode</span>
              </div>
              <div className="metric-value text-sm">{metrics?.database_mode || 'In-Memory'}</div>
            </div>

            <div className="metric-card">
              <div className="metric-header">
                <Server size={16} />
                <span>User Memories</span>
              </div>
              <div className="metric-value">{metrics?.memories_count ?? 0}</div>
            </div>
          </div>

          <div className="tools-section">
            <div className="tools-title">
              <Wrench size={14} />
              <span>Registered Tools ({metrics?.tools_available?.length || 0})</span>
            </div>
            <div className="tools-badges">
              {(metrics?.tools_available || ['calculator', 'date_time', 'weather', 'web_search', 'document_search']).map(
                (tool) => (
                  <span key={tool} className="tool-name-badge">
                    {tool}
                  </span>
                )
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default MetricsModal

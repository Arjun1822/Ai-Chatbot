import React, { useState } from 'react'
import { FileText, ExternalLink, X } from 'lucide-react'

export function CitationPill({ citation, index }) {
  const [showModal, setShowModal] = useState(false)

  return (
    <>
      <button
        type="button"
        className="citation-pill"
        onClick={() => setShowModal(true)}
        title={`View Source [${citation.source_number || index + 1}]: ${citation.filename}`}
        aria-label={`View Source ${citation.source_number || index + 1}`}
      >
        <FileText size={12} />
        <span>Source [{citation.source_number || index + 1}]: {citation.filename}</span>
        {citation.score !== undefined && (
          <span className="citation-score">{(citation.score * 100).toFixed(0)}% match</span>
        )}
      </button>

      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="citation-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="citation-dialog-header">
              <div className="citation-title-wrap">
                <FileText size={16} />
                <h4>Source [{citation.source_number || index + 1}]: {citation.filename}</h4>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => setShowModal(false)}
                aria-label="Close citation details"
              >
                <X size={16} />
              </button>
            </div>
            <div className="citation-dialog-body">
              <div className="citation-meta-row">
                <span>Document ID: <code>{citation.document_id}</code></span>
                {citation.score !== undefined && (
                  <span>Relevance Score: <code>{citation.score}</code></span>
                )}
              </div>
              <p className="citation-snippet-label">Extracted Text Chunk:</p>
              <div className="citation-snippet-box">
                {citation.snippet || 'No text snippet available.'}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default CitationPill

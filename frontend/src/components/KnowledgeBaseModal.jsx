import React, { useState, useEffect, useRef } from 'react'
import { FileUp, Trash2, X, RefreshCw, CheckCircle, FileText, AlertCircle } from 'lucide-react'
import { listDocuments, uploadDocument, deleteDocument } from '../services/api'

export function KnowledgeBaseModal({ isOpen, onClose }) {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const fileInputRef = useRef(null)

  useEffect(() => {
    if (isOpen) {
      loadDocs()
    }
  }, [isOpen])

  const loadDocs = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await listDocuments()
      setDocuments(res.data.documents || [])
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to load documents.')
    } finally {
      setLoading(false)
    }
  }

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploading(true)
    setError('')
    setSuccess('')
    try {
      const res = await uploadDocument(file)
      setSuccess(`Indexed "${file.name}" successfully (${res.data.document?.total_chunks || 1} chunks).`)
      loadDocs()
    } catch (err) {
      setError(err.response?.data?.error || 'Document upload and indexing failed.')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleDelete = async (docId, filename) => {
    try {
      await deleteDocument(docId)
      setDocuments((prev) => prev.filter((d) => d.document_id !== docId))
      setSuccess(`Deleted document "${filename}".`)
    } catch (err) {
      setError('Could not delete document.')
    }
  }

  if (!isOpen) return null

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="management-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-wrap">
            <FileText size={18} />
            <h3>RAG Knowledge Base</h3>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-description">
            Upload PDF, DOCX, Markdown, or text documents to power semantic retrieval in <strong>Document Chat</strong> mode.
          </p>

          {error && (
            <div className="modal-banner error">
              <AlertCircle size={15} />
              <span>{error}</span>
            </div>
          )}

          {success && (
            <div className="modal-banner success">
              <CheckCircle size={15} />
              <span>{success}</span>
            </div>
          )}

          {/* Upload Area */}
          <div className="upload-dropzone">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleUpload}
              accept=".pdf,.docx,.txt,.md,.markdown,.py,.js,.jsx,.ts,.tsx,.json,.csv,.sql"
              style={{ display: 'none' }}
            />
            <button
              type="button"
              className="btn-upload"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? (
                <>
                  <RefreshCw size={16} className="spin-icon" />
                  <span>Processing & Indexing Vector Chunks...</span>
                </>
              ) : (
                <>
                  <FileUp size={16} />
                  <span>Select Document to Upload (PDF, DOCX, TXT, MD)</span>
                </>
              )}
            </button>
            <span className="upload-hint">Supported formats: PDF, DOCX, TXT, MD, Code. Up to 10 MB.</span>
          </div>

          {/* Document List */}
          <div className="resource-list-section">
            <div className="resource-section-header">
              <h4>Indexed Knowledge Documents ({documents.length})</h4>
              <button type="button" className="action-icon-btn" onClick={loadDocs} title="Refresh list">
                <RefreshCw size={14} className={loading ? 'spin-icon' : ''} />
              </button>
            </div>

            <div className="resource-list">
              {documents.map((doc) => (
                <div key={doc.document_id} className="resource-item">
                  <div className="resource-info">
                    <span className="resource-name">{doc.filename}</span>
                    <div className="resource-meta">
                      <span>{doc.total_chunks || 1} chunks</span>
                      <span>•</span>
                      <span>{doc.created_at ? new Date(doc.created_at).toLocaleDateString() : 'Recent'}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="action-icon-btn danger"
                    onClick={() => handleDelete(doc.document_id, doc.filename)}
                    title="Delete document"
                    aria-label={`Delete ${doc.filename}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}

              {!documents.length && !loading && (
                <p className="empty-resource-notice">No knowledge documents uploaded yet.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default KnowledgeBaseModal

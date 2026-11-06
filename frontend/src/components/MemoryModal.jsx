import React, { useState, useEffect } from 'react'
import { Brain, Trash2, X, Plus, RefreshCw, CheckCircle, AlertCircle, Tag } from 'lucide-react'
import { listMemories, createMemory, deleteMemory } from '../services/api'

export function MemoryModal({ isOpen, onClose }) {
  const [memories, setMemories] = useState([])
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [newContent, setNewContent] = useState('')
  const [newCategory, setNewCategory] = useState('preference')
  const [newImportance, setNewImportance] = useState(3)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    if (isOpen) {
      loadMemories()
    }
  }, [isOpen, categoryFilter])

  const loadMemories = async () => {
    setLoading(true)
    setError('')
    try {
      const cat = categoryFilter === 'all' ? null : categoryFilter
      const res = await listMemories(cat)
      setMemories(res.data.memories || [])
    } catch (err) {
      setError('Failed to load user memories.')
    } finally {
      setLoading(false)
    }
  }

  const handleAdd = async (e) => {
    e.preventDefault()
    if (!newContent.trim()) return

    setSubmitting(true)
    setError('')
    setSuccess('')
    try {
      await createMemory(newContent.trim(), newCategory, Number(newImportance))
      setNewContent('')
      setSuccess('Memory saved successfully.')
      loadMemories()
    } catch (err) {
      setError(err.response?.data?.error || 'Failed to save memory.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id) => {
    try {
      await deleteMemory(id)
      setMemories((prev) => prev.filter((m) => m.id !== id))
      setSuccess('Memory removed.')
    } catch {
      setError('Could not remove memory.')
    }
  }

  if (!isOpen) return null

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="management-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-wrap">
            <Brain size={18} />
            <h3>Persistent AI Memory</h3>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-description">
            ORBIT AI remembers your preferences, project details, and explicit instructions across conversations.
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

          {/* Add Memory Form */}
          <form className="memory-add-form" onSubmit={handleAdd}>
            <div className="memory-form-row">
              <input
                type="text"
                className="memory-input"
                placeholder="e.g. Always write code with type annotations..."
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
              />
              <select
                className="memory-select"
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
              >
                <option value="preference">Preference</option>
                <option value="fact">Fact</option>
                <option value="project">Project</option>
                <option value="instruction">Instruction</option>
              </select>
              <select
                className="memory-select"
                value={newImportance}
                onChange={(e) => setNewImportance(e.target.value)}
              >
                <option value="5">P5 (High)</option>
                <option value="3">P3 (Medium)</option>
                <option value="1">P1 (Low)</option>
              </select>
              <button type="submit" className="btn-primary" disabled={submitting || !newContent.trim()}>
                <Plus size={16} /> Add
              </button>
            </div>
          </form>

          {/* Filter Pills */}
          <div className="category-filter-row">
            {['all', 'preference', 'fact', 'project', 'instruction'].map((cat) => (
              <button
                key={cat}
                type="button"
                className={`filter-chip ${categoryFilter === cat ? 'active' : ''}`}
                onClick={() => setCategoryFilter(cat)}
              >
                {cat.charAt(0).toUpperCase() + cat.slice(1)}
              </button>
            ))}
          </div>

          {/* Memory List */}
          <div className="resource-list-section">
            <div className="resource-list">
              {memories.map((mem) => (
                <div key={mem.id} className="resource-item">
                  <div className="resource-info">
                    <div className="resource-tag-row">
                      <span className={`category-tag ${mem.category}`}>
                        <Tag size={10} /> {mem.category}
                      </span>
                      <span className="importance-tag">Priority {mem.importance}/5</span>
                    </div>
                    <span className="resource-name">{mem.content}</span>
                  </div>
                  <button
                    type="button"
                    className="action-icon-btn danger"
                    onClick={() => handleDelete(mem.id)}
                    title="Delete memory"
                    aria-label="Delete memory item"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}

              {!memories.length && !loading && (
                <p className="empty-resource-notice">No stored memories found for this filter.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default MemoryModal

import React, { useState } from 'react'
import { User, LogIn, UserPlus, X, AlertCircle, CheckCircle, RefreshCw } from 'lucide-react'
import { registerUser, loginUser } from '../services/api'

export function AuthModal({ isOpen, onClose, onAuthSuccess, currentUser }) {
  const [isRegister, setIsRegister] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  if (!isOpen) return null

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!email || !password) {
      setError('Please provide email and password.')
      return
    }

    setLoading(true)
    setError('')
    setSuccess('')

    try {
      let res
      if (isRegister) {
        res = await registerUser(email, password, name)
      } else {
        res = await loginUser(email, password)
      }

      if (res.data?.token) {
        localStorage.setItem('orbit_token', res.data.token)
        setSuccess('Authenticated successfully!')
        if (onAuthSuccess) {
          onAuthSuccess(res.data.user)
        }
        setTimeout(() => {
          onClose()
        }, 600)
      }
    } catch (err) {
      setError(err.response?.data?.error || 'Authentication failed. Please check credentials.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="auth-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-wrap">
            <User size={18} />
            <h3>{isRegister ? 'Create Account' : 'Sign In to Orbit'}</h3>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-description">
            Sign in to sync your conversation threads, persistent memory, and documents across sessions.
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

          <form className="auth-form" onSubmit={handleSubmit}>
            {isRegister && (
              <div className="auth-field">
                <label>Display Name</label>
                <input
                  type="text"
                  placeholder="e.g. Alex Thorne"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
            )}
            <div className="auth-field">
              <label>Email Address</label>
              <input
                type="email"
                placeholder="developer@example.com"
                value={email}
                required
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="auth-field">
              <label>Password</label>
              <input
                type="password"
                placeholder="At least 8 characters"
                value={password}
                required
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            <button type="submit" className="btn-primary auth-submit" disabled={loading}>
              {loading ? (
                <RefreshCw size={16} className="spin-icon" />
              ) : isRegister ? (
                <>
                  <UserPlus size={16} /> Register
                </>
              ) : (
                <>
                  <LogIn size={16} /> Sign In
                </>
              )}
            </button>
          </form>

          <div className="auth-toggle-row">
            <span>{isRegister ? 'Already have an account?' : "Don't have an account yet?"}</span>
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setIsRegister(!isRegister)
                setError('')
              }}
            >
              {isRegister ? 'Sign In' : 'Create Account'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AuthModal

import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../AuthContext.jsx'
import { listMaterials, uploadMaterial } from '../api.js'

export default function MaterialsPanel({ courseId }) {
  const { token } = useAuth()
  const [materials, setMaterials] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [uploadQueue, setUploadQueue] = useState([]) // [{filename, status, error?}]
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef(null)

  useEffect(() => {
    refresh()
  }, [courseId])

  async function refresh() {
    setLoading(true)
    try {
      const data = await listMaterials(token, courseId)
      setMaterials(data)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleFilesSelected(e) {
    const files = Array.from(e.target.files)
    if (files.length === 0) return

    setUploading(true)
    setError(null)
    setUploadQueue(files.map((f) => ({ filename: f.name, status: 'pending' })))

    // Upload one at a time (not in parallel) -- keeps progress readable and
    // avoids hammering the backend/embedding model with concurrent requests.
    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      setUploadQueue((prev) => prev.map((item, idx) => idx === i ? { ...item, status: 'uploading' } : item))
      try {
        await uploadMaterial(token, courseId, file)
        setUploadQueue((prev) => prev.map((item, idx) => idx === i ? { ...item, status: 'success' } : item))
      } catch (e) {
        setUploadQueue((prev) => prev.map((item, idx) => idx === i ? { ...item, status: 'error', error: e.message } : item))
      }
    }

    setUploading(false)
    await refresh()
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  if (loading) return <div className="loading-state">Loading materials…</div>

  return (
    <div className="panel-section">
      <div className="panel-section-header">
        <h2>Reference Material</h2>
        <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          {uploading ? 'Uploading…' : 'Upload files'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".md,.txt"
          multiple
          onChange={handleFilesSelected}
          style={{ display: 'none' }}
        />
      </div>

      {error && <div className="error-banner">{error}</div>}

      {uploadQueue.length > 0 && (
        <div className="upload-queue">
          {uploadQueue.map((item, i) => (
            <div key={i} className={`upload-queue-row upload-status-${item.status}`}>
              <span className="mono">{item.filename}</span>
              <span className="upload-status-label">
                {item.status === 'pending' && 'Queued'}
                {item.status === 'uploading' && 'Uploading…'}
                {item.status === 'success' && '✓ Uploaded'}
                {item.status === 'error' && `✗ ${item.error}`}
              </span>
            </div>
          ))}
        </div>
      )}

      {materials.length === 0 ? (
        <div className="empty-state">
          No reference material uploaded yet. Upload your course's chapter files (.md or .txt) --
          they'll be chunked and embedded so the grading agent can cite them.
        </div>
      ) : (
        <div className="submission-table">
          {materials.map((m) => (
            <div key={m.filename} className="material-row">
              <span className="mono">{m.filename}</span>
              <span className="material-chunk-count">{m.chunk_count} chunks</span>
              <span className="material-date">{new Date(m.uploaded_at).toLocaleDateString()}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
import { useEffect, useState, useCallback } from 'react'
import { listSubmissions } from './api.js'
import SubmissionList from './components/Submissionlist.jsx'
import SubmissionDetail from './components/SubmissionDetail.jsx'

export default function App() {
  const [submissions, setSubmissions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedFilename, setSelectedFilename] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const data = await listSubmissions()
      setSubmissions(data)
      setError(null)
    } catch (e) {
      setError(
        `Couldn't reach the backend at http://127.0.0.1:8000 (${e.message}). ` +
        `Make sure it's running: cd backend && uvicorn main:app --reload`
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const refreshTimer = setTimeout(() => {
      refresh()
    }, 0)

    return () => clearTimeout(refreshTimer)
  }, [refresh])

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <div className="app-title">GRADEOPS<span>+</span> Review</div>
        </div>
        <div className="app-subtitle">Newton's Laws — Quiz 1</div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="loading-state">Loading submissions…</div>
      ) : selectedFilename ? (
        <SubmissionDetail
          filename={selectedFilename}
          onBack={() => setSelectedFilename(null)}
          onReviewed={async () => {
            await refresh()
            setSelectedFilename(null)
          }}
        />
      ) : (
        <SubmissionList
          submissions={submissions}
          onSelect={setSelectedFilename}
          onRefresh={refresh}
        />
      )}
    </div>
  )
}




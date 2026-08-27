import { useState } from 'react'
import { useAuth } from './AuthContext.jsx'
import LoginPage from './components/LoginPage.jsx'
import CourseSelector from './components/CourseSelector.jsx'
import RubricPanel from './components/RubricPanel.jsx'
import MaterialsPanel from './components/MaterialsPanel.jsx'
import AnswersPanel from './components/AnswersPanel.jsx'
import SubmissionDetail from './components/SubmissionDetail.jsx'

export default function App() {
  const { user, loading, logout } = useAuth()
  const [selectedCourse, setSelectedCourse] = useState(null)
  const [selectedSubmissionFilename, setSelectedSubmissionFilename] = useState(null)

  if (loading) {
    return <div className="loading-state">Loading…</div>
  }

  if (!user) {
    return <LoginPage />
  }

  if (!selectedCourse) {
    return <CourseSelector onSelect={setSelectedCourse} />
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <div className="app-title">GRADEOPS<span>+</span> Review</div>
          <div className="app-subtitle">{selectedCourse.name}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button className="btn" onClick={() => setSelectedCourse(null)}>Switch course</button>
          <span className="app-subtitle">{user.name}</span>
          <button className="btn" onClick={logout}>Log out</button>
        </div>
      </header>

      {selectedSubmissionFilename ? (
        <SubmissionDetail
          key={selectedSubmissionFilename}
          courseId={selectedCourse.id}
          filename={selectedSubmissionFilename}
          onBack={() => setSelectedSubmissionFilename(null)}
          onReviewed={() => setSelectedSubmissionFilename(null)}
        />
      ) : (
        <>
          <RubricPanel courseId={selectedCourse.id} />
          <MaterialsPanel courseId={selectedCourse.id} />
          <AnswersPanel courseId={selectedCourse.id} onSelectSubmission={setSelectedSubmissionFilename} />
        </>
      )}
    </div>
  )
}
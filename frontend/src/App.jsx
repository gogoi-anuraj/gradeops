import { useState } from 'react'
import { useAuth } from './AuthContext.jsx'
import LoginPage from './components/LoginPage.jsx'
import CourseSelector from './components/CourseSelector.jsx'
import RubricPanel from './components/RubricPanel.jsx'

export default function App() {
  const { user, loading, logout } = useAuth()
  const [selectedCourse, setSelectedCourse] = useState(null)

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

      <RubricPanel courseId={selectedCourse.id} />

      {/* Materials/answers upload + submissions list goes here next */}
    </div>
  )
}
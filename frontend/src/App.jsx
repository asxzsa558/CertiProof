import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider, theme } from 'antd'
import { useAuthStore } from './store/authStore'
import Login from './pages/Login'
import Register from './pages/Register'
import ChatPage from './pages/ChatPage'
import ModelSettings from './pages/ModelSettings'
import ResultsPage from './pages/ResultsPage'
import ResultDetailPage from './pages/ResultDetailPage'
import Dashboard from './pages/Dashboard'
import ProjectsList from './pages/ProjectsList'
import AssetsPage from './pages/AssetsPage'
import ReportsPage from './pages/ReportsPage'
import OrganizationSettings from './pages/OrganizationSettings'
import './index.css'

function ProtectedRoute({ children }) {
  const token = useAuthStore((state) => state.token)
  const hasHydrated = useAuthStore((state) => state._hasHydrated)
  const organizations = useAuthStore((state) => state.organizations)

  if (hasHydrated === false) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        background: '#0a0a0b',
        color: '#fff',
      }}>
        加载中...
      </div>
    )
  }

  if (!token) {
    return <Navigate to="/login" replace />
  }

  if (organizations.length === 0) {
    return <Navigate to="/login" replace />
  }

  return children
}

function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#00d4ff',
          borderRadius: 4,
          colorBgContainer: '#111827',
          colorBgElevated: '#1e293b',
          colorBorder: 'rgba(0, 212, 255, 0.15)',
          colorText: '#f1f5f9',
        },
        components: {
          Button: {
            borderRadius: 4,
            controlHeight: 32,
            controlHeightLG: 40,
            fontWeight: 600,
          },
          Card: {
            borderRadiusLG: 8,
          },
          Input: {
            controlHeight: 32,
            borderRadius: 4,
          },
          Menu: {
            itemBorderRadius: 4,
            itemMarginInline: 4,
          },
          Table: {
            borderRadius: 4,
          },
        },
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/projects"
            element={
              <ProtectedRoute>
                <ProjectsList />
              </ProtectedRoute>
            }
          />
          <Route
            path="/assets"
            element={
              <ProtectedRoute>
                <AssetsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/reports"
            element={
              <ProtectedRoute>
                <ReportsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/projects/:projectId"
            element={
              <ProtectedRoute>
                <ChatPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/projects/:projectId/results"
            element={
              <ProtectedRoute>
                <ResultsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/projects/:projectId/results/:scanTaskId"
            element={
              <ProtectedRoute>
                <ResultDetailPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings/models"
            element={
              <ProtectedRoute>
                <ModelSettings />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings/organization"
            element={
              <ProtectedRoute>
                <OrganizationSettings />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App

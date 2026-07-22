import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider, theme } from 'antd'
import { useAuthStore } from './store/authStore'
import './index.css'

const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const ChatPage = lazy(() => import('./pages/ChatPage'))
const ModelSettings = lazy(() => import('./pages/ModelSettings'))
const SystemSettings = lazy(() => import('./pages/SystemSettings'))
const ResultsPage = lazy(() => import('./pages/ResultsPage'))
const ResultDetailPage = lazy(() => import('./pages/ResultDetailPage'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const ProjectsList = lazy(() => import('./pages/ProjectsList'))
const ReportsPage = lazy(() => import('./pages/ReportsPage'))
const OrganizationSettings = lazy(() => import('./pages/OrganizationSettings'))
const DataLifecycleSettings = lazy(() => import('./pages/DataLifecycleSettings'))
const OperationsCenter = lazy(() => import('./pages/OperationsCenter'))
const ScanNodes = lazy(() => import('./pages/ScanNodes'))

function AppLoading() {
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

function ProtectedRoute({ children }) {
  const token = useAuthStore((state) => state.token)
  const hasHydrated = useAuthStore((state) => state._hasHydrated)
  const organizations = useAuthStore((state) => state.organizations)

  if (hasHydrated === false) {
    return <AppLoading />
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
        <Suspense fallback={<AppLoading />}>
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
                  <Navigate to="/projects?view=assets" replace />
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
              path="/operations"
              element={
                <ProtectedRoute>
                  <OperationsCenter />
                </ProtectedRoute>
              }
            />
            <Route
              path="/settings/scan-nodes"
              element={
                <ProtectedRoute>
                  <ScanNodes />
                </ProtectedRoute>
              }
            />
            <Route
              path="/settings/system"
              element={
                <ProtectedRoute>
                  <SystemSettings />
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
              path="/settings/access"
              element={
                <ProtectedRoute>
                  <OrganizationSettings />
                </ProtectedRoute>
              }
            />
            <Route
              path="/settings/data-lifecycle"
              element={
                <ProtectedRoute>
                  <DataLifecycleSettings />
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App

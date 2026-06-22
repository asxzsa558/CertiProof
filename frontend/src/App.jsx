import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider, theme } from 'antd'
import { useAuthStore } from './store/authStore'
import Login from './pages/Login'
import Register from './pages/Register'
import ChatPage from './pages/ChatPage'
import ModelSettings from './pages/ModelSettings'
import ResultsPage from './pages/ResultsPage'
import ResultDetailPage from './pages/ResultDetailPage'
import './index.css'

function ProtectedRoute({ children }) {
  const token = useAuthStore((state) => state.token)
  const hasHydrated = useAuthStore((state) => state._hasHydrated)
  
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
  return children
}

function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#6366f1',
          borderRadius: 8,
          colorBgContainer: '#111113',
          colorBgElevated: '#1a1a1c',
          colorBorder: 'rgba(255, 255, 255, 0.08)',
          colorText: 'rgba(255, 255, 255, 0.85)',
        },
        components: {
          Button: {
            borderRadius: 8,
            controlHeight: 40,
            controlHeightLG: 48,
            fontWeight: 500,
          },
          Card: {
            borderRadiusLG: 16,
          },
          Input: {
            controlHeight: 40,
            borderRadius: 8,
          },
          Menu: {
            itemBorderRadius: 8,
            itemMarginInline: 8,
          },
          Table: {
            borderRadius: 12,
          },
        },
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          
          {/* Main chat page - default route */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <ChatPage />
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
          
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App

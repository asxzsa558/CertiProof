import axios from 'axios'
import { useAuthStore } from '../store/authStore'

const api = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor
api.interceptors.request.use(
  (config) => {
    const token = useAuthStore.getState().token
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    
    // Skip refresh endpoint to avoid infinite loop
    if (originalRequest.url.includes('/auth/refresh')) {
      return Promise.reject(error)
    }
    
    // If 401 and not already retrying
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true
      
      const refreshToken = useAuthStore.getState().refreshToken
      
      if (refreshToken) {
        try {
          const response = await axios.post('/api/v1/auth/refresh', {
            refresh_token: refreshToken,
          })
          
          const { access_token, refresh_token: newRefreshToken, user } = response.data
          useAuthStore.getState().setAuth(access_token, newRefreshToken, user)
          
          originalRequest.headers.Authorization = `Bearer ${access_token}`
          return api(originalRequest)
        } catch (refreshError) {
          // Refresh failed, logout and redirect
          useAuthStore.getState().logout()
          // Use setTimeout to ensure state is saved before redirect
          setTimeout(() => {
            window.location.href = '/login'
          }, 100)
          return Promise.reject(refreshError)
        }
      } else {
        // No refresh token, logout and redirect
        useAuthStore.getState().logout()
        setTimeout(() => {
          window.location.href = '/login'
        }, 100)
      }
    }
    
    return Promise.reject(error)
  }
)

export default api

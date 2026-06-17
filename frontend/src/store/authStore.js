import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export const useAuthStore = create(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      user: null,
      
      setAuth: (token, refreshToken, user) => set({ token, refreshToken, user }),
      
      logout: () => set({ token: null, refreshToken: null, user: null }),
      
      updateUser: (user) => set({ user }),
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
      onRehydrateStorage: () => {
        return (state, error) => {
          if (error) {
            console.error('Failed to hydrate auth store:', error)
          }
        }
      },
    }
  )
)

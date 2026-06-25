import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export const useAuthStore = create(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      user: null,
      organizations: [],
      currentOrgId: null,

      setAuth: (token, refreshToken, user, organizations = []) => set({
        token,
        refreshToken,
        user,
        organizations,
        currentOrgId: organizations.length > 0 ? organizations[0].id : null,
      }),

      setOrganizations: (organizations) => set({
        organizations,
        currentOrgId: organizations.length > 0 ? organizations[0].id : null,
      }),

      setCurrentOrg: (orgId) => set({ currentOrgId: orgId }),

      logout: () => set({
        token: null,
        refreshToken: null,
        user: null,
        organizations: [],
        currentOrgId: null,
      }),

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

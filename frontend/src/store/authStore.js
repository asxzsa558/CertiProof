import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import api from '../services/api'

export const useAuthStore = create(
  persist(
    (set, get) => ({
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

      fetchOrganizations: async () => {
        const state = get()
        if (!state.token) return
        try {
          const res = await api.get('/auth/organizations')
          const orgs = res.data?.organizations || []
          set({
            organizations: orgs,
            currentOrgId: state.currentOrgId || (orgs.length > 0 ? orgs[0].id : null),
          })
        } catch (err) {
          console.error('Failed to fetch organizations:', err)
        }
      },

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

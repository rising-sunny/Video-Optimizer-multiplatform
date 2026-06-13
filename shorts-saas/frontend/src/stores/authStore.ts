import { create } from 'zustand'
import api from '../api/client'

interface User {
  id: string
  email: string
  display_name: string
  credits_remaining: number
  plan: string
}

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName: string) => Promise<void>
  logout: () => void
  loadUser: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: localStorage.getItem('access_token'),
  isAuthenticated: !!localStorage.getItem('access_token'),

  login: async (email, password) => {
    const { data } = await api.post('/auth/login', { email, password })
    localStorage.setItem('access_token', data.access_token)
    set({
      token: data.access_token,
      isAuthenticated: true,
      user: {
        id: data.user_id,
        email: data.email,
        display_name: data.display_name,
        credits_remaining: 0,
        plan: 'free',
      },
    })
  },

  register: async (email, password, displayName) => {
    const { data } = await api.post('/auth/register', {
      email,
      password,
      display_name: displayName,
    })
    localStorage.setItem('access_token', data.access_token)
    set({
      token: data.access_token,
      isAuthenticated: true,
      user: {
        id: data.user_id,
        email: data.email,
        display_name: data.display_name,
        credits_remaining: 5,
        plan: 'free',
      },
    })
  },

  logout: () => {
    localStorage.removeItem('access_token')
    set({ user: null, token: null, isAuthenticated: false })
  },

  loadUser: async () => {
    try {
      const { data } = await api.get('/auth/me')
      set({ user: data, isAuthenticated: true })
    } catch {
      set({ user: null, isAuthenticated: false })
    }
  },
}))

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { onUnauthorized, tokenStore } from '../api/client'
import { auth as authApi } from '../api/endpoints'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(tokenStore.get()))

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  useEffect(() => onUnauthorized(logout), [logout])

  useEffect(() => {
    if (!tokenStore.get()) return
    authApi
      .me()
      .then(setUser)
      .catch(() => logout())
      .finally(() => setLoading(false))
  }, [logout])

  const login = useCallback(async (email, password) => {
    const data = await authApi.login(email, password)
    tokenStore.set(data.access_token)
    setUser(data.user)
    return data.user
  }, [])

  const register = useCallback(
    async (payload) => {
      await authApi.register(payload)
      return login(payload.email, payload.password)
    },
    [login],
  )

  const value = useMemo(
    () => ({
      user,
      loading,
      login,
      register,
      logout,
      isReviewer: user?.role === 'reviewer' || user?.role === 'admin',
      isAdmin: user?.role === 'admin',
    }),
    [user, loading, login, register, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)

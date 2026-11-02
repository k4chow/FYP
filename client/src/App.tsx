import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import type { ReactElement } from 'react'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Landing from './pages/Landing'
import SignIn from './pages/SignIn'
import SignUp from './pages/SignUp'
import ForgotPassword from './pages/ForgotPassword'
import AppShell from './shell/AppShell'
import Home from './pages/Home'
import Placeholder from './pages/Placeholder'

function RequireAuth({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="center-screen muted">Loading…</div>
  if (!user) return <Navigate to="/signin" replace />
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/signin" element={<SignIn />} />
          <Route path="/signup" element={<SignUp />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route
            path="/app"
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route index element={<Home />} />
            <Route path="discover" element={<Placeholder title="Discover" phase={6} />} />
            <Route path="films" element={<Placeholder title="My Films" phase={2} />} />
            <Route path="reflections" element={<Placeholder title="My Reflections" phase={3} />} />
            <Route path="profile" element={<Placeholder title="My Profile" phase={5} />} />
            <Route path="settings" element={<Placeholder title="Settings" phase={2} />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

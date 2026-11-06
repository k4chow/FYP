import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactElement } from 'react'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Landing from './pages/Landing'
import SignIn from './pages/SignIn'
import SignUp from './pages/SignUp'
import ForgotPassword from './pages/ForgotPassword'
import AppShell from './shell/AppShell'
import Home from './pages/Home'
import MyFilms from './pages/MyFilms'
import Import from './pages/Import'
import Settings from './pages/Settings'
import Discover from './pages/Discover'
import Assistant from './pages/Assistant'
import Reflections from './pages/Reflections'
import ReflectionNew from './pages/ReflectionNew'
import ReflectionChat from './pages/ReflectionChat'
import ReviewReflection from './pages/ReviewReflection'
import Onboarding from './pages/Onboarding'
import Profile from './pages/Profile'

function RequireAuth({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="center-screen muted">Loading…</div>
  if (!user) return <Navigate to="/signin" replace />
  // New users are routed through onboarding first (only the Letterboxd
  // import step is skippable); existing/legacy accounts have the flag set
  // and never see this. The
  // reflection chat/review pages stay reachable so onboarding can open the
  // first reflection without leaving the flow.
  const allowedDuringOnboarding =
    location.pathname === '/onboarding' ||
    location.pathname.startsWith('/app/reflections/')
  if (user.onboarding_completed === false && !allowedDuringOnboarding) {
    return <Navigate to="/onboarding" replace />
  }
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/signin" element={<SignIn />} />
          <Route path="/signup" element={<SignUp />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route
            path="/onboarding"
            element={
              <RequireAuth>
                <Onboarding />
              </RequireAuth>
            }
          />
          <Route
            path="/app"
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route index element={<Home />} />
            <Route path="discover" element={<Discover />} />
            <Route path="discover/assistant" element={<Assistant />} />
            <Route path="films" element={<MyFilms />} />
            <Route path="import" element={<Import />} />
            <Route path="reflections" element={<Reflections />} />
            <Route path="reflections/new" element={<ReflectionNew />} />
            <Route path="reflections/:id/review" element={<ReviewReflection />} />
            <Route path="reflections/:id" element={<ReflectionChat />} />
            <Route path="profile" element={<Profile />} />
            <Route path="settings" element={<Settings />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

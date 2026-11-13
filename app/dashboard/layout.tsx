'use client'

import { useEffect, useState, useTransition } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import {
  Pill,
  LayoutDashboard,
  Cpu,
  Activity,
  Sparkles,
  Wrench,
  FileText,
  Users,
  Settings,
  LogOut,
  Building2,
  Shield,
  Loader2,
  Menu,
  X,
} from 'lucide-react'
import apiClient, { AuthMeResponse } from '@/lib/api-client'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [authData, setAuthData] = useState<AuthMeResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [, startTransition] = useTransition()

  useEffect(() => {
    let mounted = true
    apiClient
      .getMe()
      .then((res) => {
        if (!mounted) return
        if (res.error || !res.data) {
          // Unauthenticated: redirect to login
          router.replace('/login')
        } else {
          setAuthData(res.data)
          setLoading(false)
        }
      })
      .catch(() => {
        if (!mounted) return
        router.replace('/login')
      })

    return () => {
      mounted = false
    }
  }, [router])

  const handleLogout = async () => {
    try {
      await apiClient.logout()
    } finally {
      startTransition(() => {
        router.replace('/login')
      })
    }
  }

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-[#f8fafc]">
        <div className="flex flex-col items-center gap-3 text-slate-500">
          <Loader2 className="size-8 animate-spin text-[#1685ff]" />
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Verifying organization authorization...
          </span>
        </div>
      </div>
    )
  }

  const navLinks = [
    { label: 'Overview', href: '/dashboard', icon: LayoutDashboard },
    { label: 'Equipment', href: '/dashboard/equipment', icon: Cpu },
    { label: 'Live Monitoring', href: '/dashboard/monitoring', icon: Activity, badge: 'Live' },
    { label: 'Diagnostics', href: '/dashboard/diagnostics', icon: Sparkles, badge: 'Phase 6' },
    { label: 'Maintenance', href: '/dashboard/maintenance', icon: Wrench, badge: 'Phase 7' },
    { label: 'Factory Pilots', href: '/dashboard/pilots', icon: Shield, badge: 'Phase 9' },
    { label: 'Reports', href: '/dashboard/reports', icon: FileText, badge: 'Soon' },
    ...(authData?.permissions.is_org_admin
      ? [{ label: 'Team Members', href: '/dashboard/users', icon: Users }]
      : []),
    { label: 'Settings', href: '/dashboard/settings', icon: Settings },
  ]

  return (
    <div className="flex min-h-screen bg-[#f8fafc]">
      {/* Navy Sidebar for Desktop */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col bg-[#102c50] text-slate-200 lg:flex">
        {/* Brand header */}
        <div className="flex h-16 items-center gap-3 border-b border-white/10 px-6">
          <span className="grid size-8 place-items-center rounded-lg bg-[#0d9488] text-white">
            <Pill className="size-4" />
          </span>
          <span className="text-sm font-bold tracking-tight text-white">
            PharmaPredict <span className="text-[#61b4ff]">AI</span>
          </span>
        </div>

        {/* Current Tenant Badge */}
        <div className="border-b border-white/10 bg-white/5 px-6 py-4">
          <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-cyan-300">
            <Building2 className="size-3.5" /> Active Tenant
          </div>
          <p className="mt-1 truncate text-xs font-bold text-white">
            {authData?.organization?.name || 'Authorized Facility'}
          </p>
          <div className="mt-1.5 flex items-center gap-2">
            <span className="size-1.5 rounded-full bg-emerald-400" />
            <span className="text-[10px] text-slate-300">
              {authData?.organization?.status === 'active' ? 'Isolated & Active' : 'Restricted'}
            </span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 overflow-y-auto px-4 py-4">
          {navLinks.map((item) => {
            const Icon = item.icon
            const isActive = pathname === item.href
            return (
              <Link
                key={item.label}
                href={item.href}
                className={`flex items-center justify-between rounded-lg px-3 py-2.5 text-xs font-medium transition duration-150 ${
                  isActive
                    ? 'bg-[#1685ff] text-white shadow-md shadow-blue-500/20'
                    : 'text-slate-300 hover:bg-white/10 hover:text-white'
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon className="size-4 shrink-0" />
                  <span>{item.label}</span>
                </div>
                {item.badge && (
                  <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9px] font-semibold text-cyan-200">
                    {item.badge}
                  </span>
                )}
              </Link>
            )
          })}
        </nav>

        {/* User Card & Logout */}
        <div className="border-t border-white/10 bg-[#0c223e] p-4">
          <div className="flex items-center justify-between">
            <div className="min-w-0">
              <p className="truncate text-xs font-semibold text-white">
                {authData?.user?.full_name}
              </p>
              <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-400">
                <Shield className="size-3 text-[#61b4ff]" />
                <span className="truncate">
                  {authData?.roles?.[0] || 'Team Member'}
                </span>
              </div>
            </div>
            <button
              onClick={handleLogout}
              title="Sign out"
              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
              aria-label="Sign out"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col lg:pl-64">
        {/* Top Header */}
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-slate-200 bg-white/90 px-6 backdrop-blur">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="rounded-lg p-2 text-slate-600 lg:hidden"
              aria-label="Toggle menu"
            >
              {mobileMenuOpen ? <X className="size-5" /> : <Menu className="size-5" />}
            </button>
            <div className="hidden sm:block">
              <span className="text-xs font-semibold text-slate-500">
                {authData?.organization?.name}
              </span>
              <span className="mx-2 text-slate-300">/</span>
              <span className="text-xs font-bold text-[#102c50]">Predictive Portal</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-[11px] font-semibold text-emerald-700 sm:inline-flex">
              <span className="size-1.5 rounded-full bg-emerald-500" />
              Tenant Boundary Protected
            </span>

            <div className="flex items-center gap-2 border-l border-slate-200 pl-3">
              <div className="grid size-8 place-items-center rounded-full bg-blue-100 text-xs font-bold text-[#1685ff]">
                {authData?.user?.full_name?.charAt(0) || 'U'}
              </div>
              <button
                onClick={handleLogout}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
              >
                Sign out
              </button>
            </div>
          </div>
        </header>

        {/* Mobile menu dropdown */}
        {mobileMenuOpen && (
          <div className="border-b border-slate-200 bg-white p-4 lg:hidden">
            <div className="mb-3 border-b border-slate-100 pb-2">
              <p className="text-xs font-bold text-[#102c50]">{authData?.organization?.name}</p>
              <p className="text-[11px] text-slate-500">{authData?.user?.email}</p>
            </div>
            <nav className="space-y-1">
              {navLinks.map((item) => {
                const Icon = item.icon
                return (
                  <Link
                    key={item.label}
                    href={item.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className="flex items-center justify-between rounded-lg px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100"
                  >
                    <div className="flex items-center gap-2.5">
                      <Icon className="size-4 text-slate-500" />
                      <span>{item.label}</span>
                    </div>
                    {item.badge && (
                      <span className="text-[9px] font-bold text-[#1685ff]">{item.badge}</span>
                    )}
                  </Link>
                )
              })}
            </nav>
          </div>
        )}

        {/* Page Content */}
        <main className="flex-1 p-6 lg:p-8">{children}</main>
      </div>
    </div>
  )
}


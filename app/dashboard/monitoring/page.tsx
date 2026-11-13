'use client'

import React, { useState, useEffect, useCallback, useRef } from 'react'
import Link from 'next/link'
import {
  Activity,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Clock,
  Cpu,
  Filter,
  RefreshCw,
  Search,
  ShieldCheck,
  Building2,
  Tag,
  ArrowRight,
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
  Bell,
  PowerOff,
  Check,
  X,
  Radio,
  ExternalLink,
} from 'lucide-react'
import apiClient, {
  FleetOverviewResponse,
  FleetMachineItem,
  FleetMachinesResponse,
  FleetAlertItem,
  FleetEquipmentStatus,
} from '@/lib/api-client'

export default function FleetMonitoringPage() {
  // KPI Overview State
  const [overview, setOverview] = useState<FleetOverviewResponse | null>(null)
  const [overviewLoading, setOverviewLoading] = useState<boolean>(true)

  // Fleet Machines Grid State
  const [fleet, setFleet] = useState<FleetMachinesResponse | null>(null)
  const [fleetLoading, setFleetLoading] = useState<boolean>(true)

  // Active Alerts Drawer State
  const [alerts, setAlerts] = useState<FleetAlertItem[]>([])
  const [showAlertsPanel, setShowAlertsPanel] = useState<boolean>(false)
  const [alertsLoading, setAlertsLoading] = useState<boolean>(false)
  const [selectedAlertForAck, setSelectedAlertForAck] = useState<FleetAlertItem | null>(null)
  const [ackNotes, setAckNotes] = useState<string>('')
  const [ackLoading, setAckLoading] = useState<boolean>(false)

  // Search & Filter State
  const [searchTerm, setSearchTerm] = useState<string>('')
  const [debouncedSearch, setDebouncedSearch] = useState<string>('')
  const [selectedSite, setSelectedSite] = useState<string>('')
  const [selectedCategory, setSelectedCategory] = useState<string>('')
  const [selectedStatus, setSelectedStatus] = useState<string>('')
  const [sortBy, setSortBy] = useState<string>('severity')
  const [currentPage, setCurrentPage] = useState<number>(1)
  const pageSize = 12

  // Refresh & Polling Controls
  const [refreshInterval, setRefreshInterval] = useState<number>(10) // in seconds, 0 = paused
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date>(new Date())
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  const isMounted = useRef<boolean>(true)
  const inFlightRequest = useRef<boolean>(false)

  // Debounce search input
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(searchTerm)
      setCurrentPage(1)
    }, 350)
    return () => clearTimeout(handler)
  }, [searchTerm])

  // Fetch KPI Fleet Overview
  const fetchOverview = useCallback(async () => {
    try {
      const res = await apiClient.getFleetOverview()
      if (isMounted.current && res.data) {
        setOverview(res.data)
      }
    } catch (err: any) {
      if (isMounted.current) {
        loggerError('Failed to fetch fleet overview', err)
      }
    } finally {
      if (isMounted.current) {
        setOverviewLoading(false)
      }
    }
  }, [])

  // Fetch Fleet Machines Grid
  const fetchFleet = useCallback(async () => {
    try {
      setFleetLoading(true)
      const res = await apiClient.getFleetMachines({
        site_id: selectedSite || undefined,
        category_id: selectedCategory || undefined,
        status: selectedStatus || undefined,
        search: debouncedSearch || undefined,
        sort_by: sortBy,
        page: currentPage,
        per_page: pageSize,
      })

      if (isMounted.current && res.data) {
        setFleet(res.data)
        setError(null)
      } else if (isMounted.current && res.error) {
        setError(res.error)
      }
    } catch (err: any) {
      if (isMounted.current) {
        setError(err.message || 'Failed to fetch equipment fleet')
      }
    } finally {
      if (isMounted.current) {
        setFleetLoading(false)
      }
    }
  }, [selectedSite, selectedCategory, selectedStatus, debouncedSearch, sortBy, currentPage, pageSize])

  // Fetch Active Alerts
  const fetchAlerts = useCallback(async () => {
    try {
      setAlertsLoading(true)
      const res = await apiClient.getFleetAlerts({
        status: 'OPEN',
        limit: 50,
      })
      if (isMounted.current && res.data?.alerts) {
        setAlerts(res.data.alerts)
      }
    } catch {
      // Non-fatal
    } finally {
      if (isMounted.current) {
        setAlertsLoading(false)
      }
    }
  }, [])

  // Combined Refresh Handler
  const handleRefresh = useCallback(async () => {
    if (inFlightRequest.current) return
    inFlightRequest.current = true
    setIsRefreshing(true)

    try {
      await Promise.all([fetchOverview(), fetchFleet(), fetchAlerts()])
      if (isMounted.current) {
        setLastRefreshedAt(new Date())
      }
    } finally {
      inFlightRequest.current = false
      if (isMounted.current) {
        setIsRefreshing(false)
      }
    }
  }, [fetchOverview, fetchFleet, fetchAlerts])

  // Mount lifecycle
  useEffect(() => {
    isMounted.current = true
    handleRefresh()

    return () => {
      isMounted.current = false
    }
  }, [handleRefresh])

  // Filter change trigger
  useEffect(() => {
    fetchFleet()
  }, [fetchFleet])

  // Configurable Auto-Polling
  useEffect(() => {
    if (refreshInterval <= 0) return

    const intervalId = setInterval(() => {
      handleRefresh()
    }, refreshInterval * 1000)

    return () => clearInterval(intervalId)
  }, [refreshInterval, handleRefresh])

  // Acknowledge Alert Handler
  const handleAcknowledgeAlert = async () => {
    if (!selectedAlertForAck) return
    setAckLoading(true)
    try {
      const res = await apiClient.acknowledgeFleetAlert(selectedAlertForAck.id, ackNotes)
      if (res.data) {
        setSelectedAlertForAck(null)
        setAckNotes('')
        await fetchAlerts()
        await fetchOverview()
        await fetchFleet()
      } else {
        alert(res.error || 'Failed to acknowledge alert.')
      }
    } catch (err: any) {
      alert(err.message || 'Error acknowledging alert.')
    } finally {
      setAckLoading(false)
    }
  }

  // Clear all filters
  const handleClearFilters = () => {
    setSearchTerm('')
    setDebouncedSearch('')
    setSelectedSite('')
    setSelectedCategory('')
    setSelectedStatus('')
    setSortBy('severity')
    setCurrentPage(1)
  }

  const hasActiveFilters = Boolean(
    searchTerm || selectedSite || selectedCategory || selectedStatus || sortBy !== 'severity'
  )

  // Status Styling Badge
  const getStatusBadge = (status: FleetEquipmentStatus) => {
    switch (status) {
      case 'CRITICAL':
        return {
          bg: 'bg-rose-50 text-rose-700 border-rose-200',
          dot: 'bg-rose-500 animate-ping',
          icon: AlertCircle,
          label: 'CRITICAL',
        }
      case 'WARNING':
        return {
          bg: 'bg-amber-50 text-amber-700 border-amber-200',
          dot: 'bg-amber-500',
          icon: AlertTriangle,
          label: 'WARNING',
        }
      case 'HEALTHY':
        return {
          bg: 'bg-emerald-50 text-emerald-700 border-emerald-200',
          dot: 'bg-emerald-500',
          icon: CheckCircle2,
          label: 'HEALTHY',
        }
      case 'STALE':
        return {
          bg: 'bg-yellow-50 text-yellow-800 border-yellow-200',
          dot: 'bg-yellow-500',
          icon: Clock,
          label: 'STALE TELEMETRY',
        }
      case 'OFFLINE':
        return {
          bg: 'bg-slate-100 text-slate-700 border-slate-200',
          dot: 'bg-slate-400',
          icon: PowerOff,
          label: 'OFFLINE',
        }
      case 'NOT CONFIGURED':
      default:
        return {
          bg: 'bg-slate-50 text-slate-500 border-slate-200 border-dashed',
          dot: 'bg-slate-300',
          icon: SlidersHorizontal,
          label: 'NOT CONFIGURED',
        }
    }
  }

  return (
    <div className="space-y-6 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
      {/* Top Header & Fleet Observability Controls */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="grid size-10 place-items-center rounded-xl bg-blue-50 text-[#1685ff]">
              <Activity className="size-5" />
            </span>
            <div>
              <h1 className="text-xl font-black text-[#102c50] tracking-tight">
                Plant-Wide Observability &amp; Fleet Monitoring
              </h1>
              <p className="text-xs text-slate-500">
                Continuous pharmaceutical equipment health, live telemetry streams &amp; threshold monitoring
              </p>
            </div>
          </div>
        </div>

        {/* Polling & Refresh Bar */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Active Alarms Drawer Toggle */}
          <button
            onClick={() => setShowAlertsPanel(!showAlertsPanel)}
            className={`relative inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-bold transition shadow-xs ${
              alerts.length > 0
                ? 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100'
                : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
            }`}
          >
            <Bell className={`size-3.5 ${alerts.length > 0 ? 'text-rose-600 animate-pulse' : 'text-slate-500'}`} />
            <span>Alarms ({alerts.length})</span>
            {alerts.length > 0 && (
              <span className="absolute -top-1.5 -right-1.5 size-4 rounded-full bg-rose-500 text-[10px] font-black text-white grid place-items-center">
                {alerts.length}
              </span>
            )}
          </button>

          {/* Refresh Frequency Select */}
          <div className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 shadow-xs">
            <span className="text-[11px] font-semibold text-slate-400">POLL:</span>
            <select
              value={refreshInterval}
              onChange={(e) => setRefreshInterval(Number(e.target.value))}
              className="bg-transparent font-bold text-slate-700 focus:outline-hidden cursor-pointer"
            >
              <option value="5">5s (Fast)</option>
              <option value="10">10s (Standard)</option>
              <option value="30">30s (Slow)</option>
              <option value="0">Paused</option>
            </select>
          </div>

          {/* Refresh Button */}
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-xs transition hover:bg-slate-50 disabled:opacity-50"
            title="Refresh fleet data"
          >
            <RefreshCw className={`size-3.5 text-slate-500 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>

          {/* Last Refreshed Badge */}
          <div className="hidden md:flex items-center gap-1 rounded-xl bg-slate-100 px-3 py-2 text-[11px] font-mono text-slate-500">
            <Clock className="size-3 text-slate-400" />
            <span>{lastRefreshedAt.toLocaleTimeString()}</span>
          </div>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="flex items-center justify-between gap-2 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs font-semibold text-rose-800">
          <div className="flex items-center gap-2">
            <AlertCircle className="size-4 text-rose-600 shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={handleRefresh} className="rounded-lg bg-rose-600 px-3 py-1 font-bold text-white hover:bg-rose-700">
            Retry
          </button>
        </div>
      )}

      {/* 1. Plant-Wide KPI Summary Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        {/* Total Equipment */}
        <div
          onClick={() => setSelectedStatus('')}
          className={`cursor-pointer rounded-2xl border p-4 transition shadow-xs hover:shadow-md ${
            selectedStatus === '' ? 'border-[#1685ff] bg-blue-50/20 ring-1 ring-blue-100' : 'border-slate-200 bg-white'
          }`}
        >
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">TOTAL FLEET</span>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-[#102c50]">
              {overviewLoading ? '--' : overview?.total_equipment ?? 0}
            </span>
            <Cpu className="size-4 text-slate-400" />
          </div>
          <span className="mt-1 block text-[10px] text-slate-400">Registered assets</span>
        </div>

        {/* Currently Monitoring */}
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">MONITORING</span>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-[#1685ff]">
              {overviewLoading ? '--' : overview?.monitoring_equipment ?? 0}
            </span>
            <Radio className="size-4 text-[#1685ff] animate-pulse" />
          </div>
          <span className="mt-1 block text-[10px] text-slate-400">Active pipelines</span>
        </div>

        {/* Healthy */}
        <div
          onClick={() => setSelectedStatus('HEALTHY')}
          className={`cursor-pointer rounded-2xl border p-4 transition shadow-xs hover:shadow-md ${
            selectedStatus === 'HEALTHY' ? 'border-emerald-300 bg-emerald-50/40 ring-1 ring-emerald-200' : 'border-slate-200 bg-white'
          }`}
        >
          <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-600">HEALTHY</span>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-emerald-600">
              {overviewLoading ? '--' : overview?.healthy_equipment ?? 0}
            </span>
            <CheckCircle2 className="size-4 text-emerald-500" />
          </div>
          <span className="mt-1 block text-[10px] text-slate-400">In limits, fresh</span>
        </div>

        {/* Warning */}
        <div
          onClick={() => setSelectedStatus('WARNING')}
          className={`cursor-pointer rounded-2xl border p-4 transition shadow-xs hover:shadow-md ${
            selectedStatus === 'WARNING' ? 'border-amber-300 bg-amber-50/40 ring-1 ring-amber-200' : 'border-slate-200 bg-white'
          }`}
        >
          <span className="text-[10px] font-bold uppercase tracking-wider text-amber-600">WARNING</span>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-amber-600">
              {overviewLoading ? '--' : overview?.warning_equipment ?? 0}
            </span>
            <AlertTriangle className="size-4 text-amber-500" />
          </div>
          <span className="mt-1 block text-[10px] text-slate-400">Drift / alert</span>
        </div>

        {/* Critical */}
        <div
          onClick={() => setSelectedStatus('CRITICAL')}
          className={`cursor-pointer rounded-2xl border p-4 transition shadow-xs hover:shadow-md ${
            selectedStatus === 'CRITICAL' ? 'border-rose-300 bg-rose-50/40 ring-1 ring-rose-200' : 'border-slate-200 bg-white'
          }`}
        >
          <span className="text-[10px] font-bold uppercase tracking-wider text-rose-600">CRITICAL</span>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-rose-600">
              {overviewLoading ? '--' : overview?.critical_equipment ?? 0}
            </span>
            <AlertCircle className="size-4 text-rose-500 animate-bounce" />
          </div>
          <span className="mt-1 block text-[10px] text-slate-400">Threshold breach</span>
        </div>

        {/* Stale Telemetry */}
        <div
          onClick={() => setSelectedStatus('STALE')}
          className={`cursor-pointer rounded-2xl border p-4 transition shadow-xs hover:shadow-md ${
            selectedStatus === 'STALE' ? 'border-yellow-300 bg-yellow-50/40 ring-1 ring-yellow-200' : 'border-slate-200 bg-white'
          }`}
        >
          <span className="text-[10px] font-bold uppercase tracking-wider text-yellow-700">STALE</span>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-yellow-700">
              {overviewLoading ? '--' : overview?.stale_equipment ?? 0}
            </span>
            <Clock className="size-4 text-yellow-600" />
          </div>
          <span className="mt-1 block text-[10px] text-slate-400">Delayed stream</span>
        </div>

        {/* Offline */}
        <div
          onClick={() => setSelectedStatus('OFFLINE')}
          className={`cursor-pointer rounded-2xl border p-4 transition shadow-xs hover:shadow-md ${
            selectedStatus === 'OFFLINE' ? 'border-slate-400 bg-slate-100 ring-1 ring-slate-300' : 'border-slate-200 bg-white'
          }`}
        >
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">OFFLINE</span>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-slate-700">
              {overviewLoading ? '--' : overview?.offline_equipment ?? 0}
            </span>
            <PowerOff className="size-4 text-slate-400" />
          </div>
          <span className="mt-1 block text-[10px] text-slate-400">Stopped monitor</span>
        </div>

        {/* Active Alarms */}
        <div
          onClick={() => setShowAlertsPanel(true)}
          className="cursor-pointer rounded-2xl border border-rose-200 bg-rose-50/50 p-4 shadow-xs transition hover:bg-rose-50 hover:shadow-md"
        >
          <span className="text-[10px] font-bold uppercase tracking-wider text-rose-700">ALARMS</span>
          <div className="mt-1 flex items-baseline justify-between">
            <span className="font-mono text-2xl font-black text-rose-700">
              {overviewLoading ? '--' : overview?.active_alerts_count ?? 0}
            </span>
            <Bell className="size-4 text-rose-600 animate-pulse" />
          </div>
          <span className="mt-1 block text-[10px] text-rose-600 font-semibold truncate">
            {overview?.critical_alerts_count ?? 0} Crit / {overview?.warning_alerts_count ?? 0} Warn
          </span>
        </div>
      </div>

      {/* 2. Active Alarms Centralized Panel (Collapsible) */}
      {showAlertsPanel && (
        <div className="rounded-2xl border border-rose-200 bg-white p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-rose-100 pb-3">
            <div className="flex items-center gap-2">
              <Bell className="size-4 text-rose-600" />
              <h2 className="text-sm font-bold text-[#102c50]">Centralized Plant Alarms Overview</h2>
              <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-bold text-rose-700">
                {alerts.length} Active
              </span>
            </div>
            <button
              onClick={() => setShowAlertsPanel(false)}
              className="text-slate-400 hover:text-slate-700"
            >
              <X className="size-4" />
            </button>
          </div>

          {alertsLoading ? (
            <div className="py-8 text-center text-xs text-slate-400">
              <RefreshCw className="mx-auto size-5 animate-spin text-slate-400 mb-2" />
              Loading active plant alarms...
            </div>
          ) : alerts.length === 0 ? (
            <div className="py-6 text-center text-xs text-slate-500">
              <CheckCircle2 className="mx-auto size-6 text-emerald-500 mb-1" />
              <p className="font-semibold text-slate-700">No Active Alarms in Fleet</p>
              <p className="text-[11px] text-slate-400">All registered equipment telemetry operating within approved thresholds.</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100 max-h-72 overflow-y-auto">
              {alerts.map((alert) => (
                <div key={alert.id} className="py-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-xs">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-black uppercase ${
                          alert.severity === 'CRITICAL' ? 'bg-rose-100 text-rose-700' : 'bg-amber-100 text-amber-700'
                        }`}
                      >
                        {alert.severity}
                      </span>
                      <span className="font-bold text-slate-800">{alert.equipment_name}</span>
                      <span className="font-mono text-slate-400">({alert.asset_code})</span>
                      <span className="text-slate-400">· {alert.site_name}</span>
                    </div>
                    <p className="text-slate-600">
                      Signal: <span className="font-semibold">{alert.signal_name}</span>
                      {alert.observed_value !== null && alert.observed_value !== undefined && (
                        <span> · Observed Value: <span className="font-mono font-bold text-slate-800">{alert.observed_value.toFixed(2)}</span></span>
                      )}
                      {alert.anomaly_summary && <span> — {alert.anomaly_summary}</span>}
                    </p>
                    <p className="text-[11px] text-slate-400 font-mono">
                      Detected: {alert.last_detected_at ? new Date(alert.last_detected_at).toLocaleString() : 'Recent'}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => setSelectedAlertForAck(alert)}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 shadow-xs hover:bg-slate-50"
                    >
                      <Check className="size-3 text-emerald-600" />
                      <span>Acknowledge</span>
                    </button>

                    <Link
                      href={`/dashboard/equipment/${alert.machine_id}`}
                      className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2.5 py-1 text-xs font-bold text-[#1685ff] hover:bg-blue-100"
                    >
                      <span>Inspect</span>
                      <ArrowRight className="size-3" />
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 3. Search, Filter & Sort Controls Bar */}
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {/* Search Box */}
          <div className="relative">
            <Search className="absolute left-3 top-2.5 size-4 text-slate-400" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search by equipment name or code..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50/50 pl-9 pr-3 py-2 text-xs text-slate-800 focus:bg-white focus:outline-hidden focus:ring-1 focus:ring-[#1685ff]"
            />
          </div>

          {/* Site / Location Filter */}
          <div className="relative">
            <Building2 className="absolute left-3 top-2.5 size-4 text-slate-400 pointer-events-none" />
            <select
              value={selectedSite}
              onChange={(e) => {
                setSelectedSite(e.target.value)
                setCurrentPage(1)
              }}
              className="w-full rounded-xl border border-slate-200 bg-slate-50/50 pl-9 pr-3 py-2 text-xs text-slate-700 focus:bg-white focus:outline-hidden focus:ring-1 focus:ring-[#1685ff]"
            >
              <option value="">All Production Areas / Sites</option>
              {fleet?.sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name} ({site.count})
                </option>
              ))}
            </select>
          </div>

          {/* Equipment Category Filter */}
          <div className="relative">
            <Tag className="absolute left-3 top-2.5 size-4 text-slate-400 pointer-events-none" />
            <select
              value={selectedCategory}
              onChange={(e) => {
                setSelectedCategory(e.target.value)
                setCurrentPage(1)
              }}
              className="w-full rounded-xl border border-slate-200 bg-slate-50/50 pl-9 pr-3 py-2 text-xs text-slate-700 focus:bg-white focus:outline-hidden focus:ring-1 focus:ring-[#1685ff]"
            >
              <option value="">All Equipment Types</option>
              {fleet?.categories.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.name} ({cat.count})
                </option>
              ))}
            </select>
          </div>

          {/* Status Filter */}
          <div className="relative">
            <Filter className="absolute left-3 top-2.5 size-4 text-slate-400 pointer-events-none" />
            <select
              value={selectedStatus}
              onChange={(e) => {
                setSelectedStatus(e.target.value)
                setCurrentPage(1)
              }}
              className="w-full rounded-xl border border-slate-200 bg-slate-50/50 pl-9 pr-3 py-2 text-xs text-slate-700 focus:bg-white focus:outline-hidden focus:ring-1 focus:ring-[#1685ff]"
            >
              <option value="">All Monitoring Statuses</option>
              <option value="CRITICAL">Critical</option>
              <option value="WARNING">Warning</option>
              <option value="HEALTHY">Healthy</option>
              <option value="STALE">Stale Telemetry</option>
              <option value="OFFLINE">Offline</option>
              <option value="NOT CONFIGURED">Not Configured</option>
            </select>
          </div>

          {/* Sort By Filter */}
          <div className="relative">
            <SlidersHorizontal className="absolute left-3 top-2.5 size-4 text-slate-400 pointer-events-none" />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-slate-50/50 pl-9 pr-3 py-2 text-xs text-slate-700 focus:bg-white focus:outline-hidden focus:ring-1 focus:ring-[#1685ff]"
            >
              <option value="severity">Sort: Highest Severity</option>
              <option value="latest_telemetry">Sort: Latest Telemetry</option>
              <option value="name">Sort: Equipment Name</option>
              <option value="asset_code">Sort: Asset Code</option>
            </select>
          </div>
        </div>

        {/* Filter Summary Tags */}
        {hasActiveFilters && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-2 text-xs">
            <div className="flex flex-wrap items-center gap-1.5 text-slate-500">
              <span className="font-semibold text-slate-400">Active Filters:</span>
              {selectedStatus && (
                <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-700">
                  Status: {selectedStatus}
                  <button onClick={() => setSelectedStatus('')} className="hover:text-rose-600">
                    <X className="size-3" />
                  </button>
                </span>
              )}
              {selectedSite && (
                <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-700">
                  Area: {fleet?.sites.find((s) => s.id === selectedSite)?.name || selectedSite}
                  <button onClick={() => setSelectedSite('')} className="hover:text-rose-600">
                    <X className="size-3" />
                  </button>
                </span>
              )}
              {selectedCategory && (
                <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-700">
                  Type: {fleet?.categories.find((c) => c.id === selectedCategory)?.name || selectedCategory}
                  <button onClick={() => setSelectedCategory('')} className="hover:text-rose-600">
                    <X className="size-3" />
                  </button>
                </span>
              )}
              {searchTerm && (
                <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-700">
                  Search: &quot;{searchTerm}&quot;
                  <button onClick={() => setSearchTerm('')} className="hover:text-rose-600">
                    <X className="size-3" />
                  </button>
                </span>
              )}
            </div>

            <button
              onClick={handleClearFilters}
              className="text-[11px] font-bold text-[#1685ff] hover:underline"
            >
              Reset All Filters
            </button>
          </div>
        )}
      </div>

      {/* 4. Equipment Fleet Monitoring Grid */}
      {fleetLoading && !fleet ? (
        <div className="py-16 text-center text-xs text-slate-400">
          <RefreshCw className="mx-auto size-6 animate-spin text-[#1685ff] mb-2" />
          Querying plant fleet operational health...
        </div>
      ) : !fleet || fleet.items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center">
          <Cpu className="mx-auto size-8 text-slate-400 mb-2" />
          <h3 className="text-sm font-bold text-slate-700">No Equipment Matches Criteria</h3>
          <p className="mt-1 text-xs text-slate-500 max-w-sm mx-auto">
            Try adjusting your search query, clearing status filters, or registering new equipment in the equipment directory.
          </p>
          {hasActiveFilters && (
            <button
              onClick={handleClearFilters}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[#1685ff] px-3.5 py-2 text-xs font-semibold text-white shadow-xs hover:bg-[#126bd0]"
            >
              Clear Filters
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between text-xs text-slate-500 px-1">
            <span>
              Showing <span className="font-bold text-slate-700">{(fleet.page - 1) * fleet.per_page + 1}</span>–
              <span className="font-bold text-slate-700">{Math.min(fleet.total, fleet.page * fleet.per_page)}</span> of{' '}
              <span className="font-bold text-slate-700">{fleet.total}</span> assets
            </span>
            <span className="hidden sm:inline">Click any asset card to open continuous sensor stream</span>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {fleet.items.map((item) => {
              const badge = getStatusBadge(item.status)
              const BadgeIcon = badge.icon

              return (
                <Link
                  key={item.id}
                  href={`/dashboard/equipment/${item.id}`}
                  className="group relative rounded-2xl border border-slate-200 bg-white p-5 shadow-xs transition hover:border-[#1685ff]/50 hover:shadow-md flex flex-col justify-between"
                >
                  <div className="space-y-3">
                    {/* Header Row: Type and Status */}
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 truncate max-w-[140px]" title={item.equipment_type}>
                        {item.equipment_type}
                      </span>

                      <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold shrink-0 ${badge.bg}`}>
                        <span className={`size-1.5 rounded-full ${badge.dot}`} />
                        {badge.label}
                      </span>
                    </div>

                    {/* Machine Name & Asset Code */}
                    <div>
                      <h4 className="font-bold text-[#102c50] text-sm group-hover:text-[#1685ff] transition truncate" title={item.equipment_name}>
                        {item.equipment_name}
                      </h4>
                      <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500">
                        <span className="font-mono font-semibold text-slate-700">{item.asset_code}</span>
                        <span>·</span>
                        <span className="truncate">{item.location}</span>
                      </div>
                    </div>

                    {/* Threshold Breach Badges if any */}
                    {item.threshold_breaches && item.threshold_breaches.length > 0 && (
                      <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-2.5 text-[11px] text-rose-800 space-y-1">
                        <span className="font-bold block text-[10px] uppercase tracking-wider text-rose-700">
                          Active Breaches:
                        </span>
                        {item.threshold_breaches.slice(0, 2).map((br, idx) => (
                          <div key={idx} className="flex items-center justify-between font-mono text-[10px]">
                            <span className="truncate font-semibold">{br.signal_id}</span>
                            <span className="font-bold">{br.value.toFixed(1)} {br.unit}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Footer Telemetry Row */}
                  <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
                    <div className="flex items-center gap-1.5 truncate">
                      <Clock className="size-3 text-slate-400 shrink-0" />
                      <span className="truncate">
                        {item.latest_telemetry_at
                          ? item.telemetry_age_seconds !== null && item.telemetry_age_seconds !== undefined
                            ? item.telemetry_age_seconds < 60
                              ? `${Math.round(item.telemetry_age_seconds)}s ago`
                              : `${Math.round(item.telemetry_age_seconds / 60)}m ago`
                            : 'Active'
                          : 'No data'}
                      </span>
                    </div>

                    <div className="flex items-center gap-1 shrink-0 font-semibold text-[#1685ff] group-hover:translate-x-0.5 transition">
                      <span>Stream</span>
                      <ExternalLink className="size-3" />
                    </div>
                  </div>
                </Link>
              )
            })}
          </div>

          {/* 5. Pagination Bar */}
          {fleet.pages > 1 && (
            <div className="flex items-center justify-between border-t border-slate-200 pt-4 text-xs">
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 shadow-xs hover:bg-slate-50 disabled:opacity-50"
              >
                <ChevronLeft className="size-3.5" />
                <span>Previous</span>
              </button>

              <span className="text-slate-500">
                Page <span className="font-bold text-slate-800">{fleet.page}</span> of{' '}
                <span className="font-bold text-slate-800">{fleet.pages}</span>
              </span>

              <button
                onClick={() => setCurrentPage((p) => Math.min(fleet.pages, p + 1))}
                disabled={currentPage >= fleet.pages}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 shadow-xs hover:bg-slate-50 disabled:opacity-50"
              >
                <span>Next</span>
                <ChevronRight className="size-3.5" />
              </button>
            </div>
          )}
        </div>
      )}

      {/* Acknowledge Alert Confirmation Modal */}
      {selectedAlertForAck && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="font-bold text-[#102c50]">Acknowledge Equipment Alarm</h3>
                <p className="text-xs text-slate-500">
                  Asset: <span className="font-semibold text-slate-700">{selectedAlertForAck.equipment_name}</span> ({selectedAlertForAck.asset_code})
                </p>
              </div>
              <button onClick={() => setSelectedAlertForAck(null)} className="text-slate-400 hover:text-slate-700">
                <X className="size-5" />
              </button>
            </div>

            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-xs space-y-1">
              <p>
                <span className="font-semibold text-slate-500">Signal:</span> {selectedAlertForAck.signal_name}
              </p>
              <p>
                <span className="font-semibold text-slate-500">Severity:</span>{' '}
                <span className={`font-bold uppercase ${selectedAlertForAck.severity === 'CRITICAL' ? 'text-rose-600' : 'text-amber-600'}`}>
                  {selectedAlertForAck.severity}
                </span>
              </p>
              {selectedAlertForAck.observed_value !== null && selectedAlertForAck.observed_value !== undefined && (
                <p>
                  <span className="font-semibold text-slate-500">Observed Value:</span>{' '}
                  <span className="font-mono font-bold text-slate-800">{selectedAlertForAck.observed_value.toFixed(2)}</span>
                </p>
              )}
            </div>

            <div className="space-y-1 text-xs">
              <label className="font-semibold text-slate-700 block">Operator / Engineering Notes</label>
              <textarea
                value={ackNotes}
                onChange={(e) => setAckNotes(e.target.value)}
                placeholder="Enter actions taken or investigation rationale..."
                rows={3}
                className="w-full rounded-xl border border-slate-300 p-2.5 text-xs text-slate-800 focus:outline-hidden focus:ring-1 focus:ring-[#1685ff]"
              />
              <span className="text-[11px] text-slate-400">
                Strict audit trail: Acknowledgment recorded with authenticated user timestamp.
              </span>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
              <button
                type="button"
                onClick={() => setSelectedAlertForAck(null)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleAcknowledgeAlert}
                disabled={ackLoading}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-bold text-white shadow-xs hover:bg-emerald-700 disabled:opacity-50"
              >
                <Check className="size-3.5" />
                <span>{ackLoading ? 'Recording...' : 'Confirm Acknowledgment'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function loggerError(msg: string, err: any) {
  if (process.env.NODE_ENV !== 'production') {
    // eslint-disable-next-line no-console
    console.error(msg, err)
  }
}

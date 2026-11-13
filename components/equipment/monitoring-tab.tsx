'use client'

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  Activity,
  Play,
  Square,
  RefreshCw,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Clock,
  Database,
  Radio,
  Sliders,
  TrendingUp,
  ShieldCheck,
  Server,
  Download,
  Eye,
  EyeOff,
  Layers,
  Settings,
  Calendar,
  X,
  Check,
  ChevronRight,
} from 'lucide-react'
import {
  apiClient,
  MonitoringStatusResponse,
  SignalReadingItem,
  MonitoringState,
  SignalFreshness,
  SignalThresholdItem,
} from '@/lib/api-client'

interface MonitoringTabProps {
  machineId: string
  machineName: string
  onSwitchToMapping?: () => void
}

// Consistent high-contrast color palette for multi-signal overlays
const SIGNAL_COLORS = [
  '#1685ff', // Primary Blue
  '#10b981', // Emerald Green
  '#f59e0b', // Amber / Orange
  '#8b5cf6', // Violet
  '#ec4899', // Pink
  '#06b6d4', // Cyan
  '#f97316', // Bright Orange
  '#6366f1', // Indigo
]

export default function MonitoringTab({
  machineId,
  machineName,
  onSwitchToMapping,
}: MonitoringTabProps) {
  const [status, setStatus] = useState<MonitoringStatusResponse | null>(null)
  const [readings, setReadings] = useState<SignalReadingItem[]>([])
  const [history, setHistory] = useState<SignalReadingItem[]>([])
  const [thresholds, setThresholds] = useState<Record<string, SignalThresholdItem>>({})

  // Multi-Signal Selection & Visibility
  const [selectedSignalIds, setSelectedSignalIds] = useState<string[]>([])
  const [hiddenSignalIds, setHiddenSignalIds] = useState<Set<string>>(new Set())

  // Time Range & Downsampling Controls
  const [timeWindow, setTimeWindow] = useState<'15m' | '1h' | '6h' | '24h' | 'custom'>('1h')
  const [customStart, setCustomStart] = useState<string>('')
  const [customEnd, setCustomEnd] = useState<string>('')

  // Chart Scaling & Visual Settings
  const [scaleMode, setScaleMode] = useState<'relative' | 'raw'>('relative')
  const [focusedSignalId, setFocusedSignalId] = useState<string | null>(null)

  // Status & Loading States
  const [loading, setLoading] = useState<boolean>(true)
  const [chartLoading, setChartLoading] = useState<boolean>(false)
  const [actionLoading, setActionLoading] = useState<boolean>(false)
  const [exportLoading, setExportLoading] = useState<string | null>(null) // 'csv' | 'json' | null
  const [autoPoll, setAutoPoll] = useState<boolean>(true)
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date())
  const [error, setError] = useState<string | null>(null)
  const [exportSuccessMsg, setExportSuccessMsg] = useState<string | null>(null)

  // Threshold Configuration Modal State
  const [configModalSignal, setConfigModalSignal] = useState<SignalReadingItem | null>(null)
  const [modalWarnMin, setModalWarnMin] = useState<string>('')
  const [modalWarnMax, setModalWarnMax] = useState<string>('')
  const [modalCritMin, setModalCritMin] = useState<string>('')
  const [modalCritMax, setModalCritMax] = useState<string>('')
  const [modalNotes, setModalNotes] = useState<string>('')
  const [modalSaving, setModalSaving] = useState<boolean>(false)
  const [modalError, setModalError] = useState<string | null>(null)

  // Gateway Endpoint Configuration
  const [endpointUrl, setEndpointUrl] = useState<string>('opc.tcp://127.0.0.1:48401/pharmapredict/server/')
  const [showConfig, setShowConfig] = useState<boolean>(false)

  const isMounted = useRef<boolean>(true)

  // Fetch thresholds
  const fetchThresholds = useCallback(async () => {
    try {
      const res = await apiClient.getEquipmentThresholds(machineId)
      if (res.data?.thresholds) {
        setThresholds(res.data.thresholds)
      }
    } catch {
      // Non-fatal
    }
  }, [machineId])

  // Fetch status and latest sensor telemetry
  const fetchLiveData = useCallback(
    async (isInitial = false) => {
      if (isInitial) setLoading(true)
      setError(null)

      try {
        const [statusRes, latestRes] = await Promise.all([
          apiClient.getMonitoringStatus(machineId),
          apiClient.getLatestReadings(machineId),
        ])

        if (!isMounted.current) return

        if (statusRes.data) {
          setStatus(statusRes.data)
        } else if (statusRes.error) {
          setError(statusRes.error)
        }

        if (latestRes.data?.readings) {
          const newReadings = latestRes.data.readings
          setReadings(newReadings)

          // Auto-select initial 2-3 signals for multi-signal overlay if none selected
          setSelectedSignalIds((prev) => {
            if (prev.length > 0) return prev
            return newReadings.slice(0, 3).map((r) => r.signal_id)
          })
        }

        setLastRefreshed(new Date())
      } catch (err: unknown) {
        if (isMounted.current) {
          setError(err instanceof Error ? err.message : 'Failed to fetch live monitoring telemetry')
        }
      } finally {
        if (isMounted.current && isInitial) {
          setLoading(false)
        }
      }
    },
    [machineId]
  )

  // Compute effective query time range
  const getTimeRangeBounds = useCallback((): { start: Date; end: Date } => {
    const now = new Date()
    if (timeWindow === 'custom' && customStart && customEnd) {
      return {
        start: new Date(customStart),
        end: new Date(customEnd),
      }
    }
    let start: Date
    switch (timeWindow) {
      case '15m':
        start = new Date(now.getTime() - 15 * 60 * 1000)
        break
      case '1h':
        start = new Date(now.getTime() - 60 * 60 * 1000)
        break
      case '6h':
        start = new Date(now.getTime() - 6 * 60 * 60 * 1000)
        break
      case '24h':
      default:
        start = new Date(now.getTime() - 24 * 60 * 60 * 1000)
        break
    }
    return { start, end: now }
  }, [timeWindow, customStart, customEnd])

  // Fetch historical time series for selected signals
  const fetchHistory = useCallback(async () => {
    if (selectedSignalIds.length === 0) {
      setHistory([])
      return
    }

    const { start, end } = getTimeRangeBounds()

    try {
      setChartLoading(true)
      const res = await apiClient.getHistoricalReadings(machineId, {
        signal_ids: selectedSignalIds,
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        limit: 1000,
        downsample: 'auto',
      })

      if (isMounted.current && res.data?.readings) {
        const resData = res.data
        setHistory(resData.readings)
        if (resData.thresholds) {
          const freshThresholds = resData.thresholds
          setThresholds((prev) => ({ ...prev, ...freshThresholds }))
        }
      }
    } catch {
      // Non-fatal background fetch
    } finally {
      if (isMounted.current) {
        setChartLoading(false)
      }
    }
  }, [machineId, selectedSignalIds, getTimeRangeBounds])

  // Mount lifecycle
  useEffect(() => {
    isMounted.current = true
    fetchLiveData(true)
    fetchThresholds()

    return () => {
      isMounted.current = false
    }
  }, [fetchLiveData, fetchThresholds])

  // Chart data fetch when signals or time window changes
  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  // Auto-polling interval (2s)
  useEffect(() => {
    if (!autoPoll) return

    const intervalId = setInterval(() => {
      fetchLiveData(false)
      if (status?.observed_state === 'ACTIVE' || status?.observed_state === 'DEGRADED') {
        fetchHistory()
      }
    }, 2500)

    return () => clearInterval(intervalId)
  }, [autoPoll, fetchLiveData, fetchHistory, status?.observed_state])

  // Activation & Deactivation Handlers
  const handleActivate = async () => {
    setActionLoading(true)
    setError(null)
    try {
      const res = await apiClient.activateMonitoring(
        machineId,
        endpointUrl.trim() || undefined
      )
      if (res.data) {
        await fetchLiveData(false)
      } else {
        setError(res.error || 'Failed to activate monitoring.')
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Activation error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleDeactivate = async () => {
    setActionLoading(true)
    setError(null)
    try {
      const res = await apiClient.deactivateMonitoring(machineId)
      if (res.data) {
        await fetchLiveData(false)
      } else {
        setError(res.error || 'Failed to deactivate monitoring.')
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Deactivation error')
    } finally {
      setActionLoading(false)
    }
  }

  // Toggle Signal Selection
  const toggleSignalSelection = (sigId: string) => {
    setSelectedSignalIds((prev) => {
      if (prev.includes(sigId)) {
        if (prev.length === 1) return prev // keep at least 1 selected
        return prev.filter((id) => id !== sigId)
      } else {
        return [...prev, sigId]
      }
    })
  }

  // Toggle Signal Visibility in Chart
  const toggleSignalVisibility = (sigId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setHiddenSignalIds((prev) => {
      const next = new Set(prev)
      if (next.has(sigId)) {
        next.delete(sigId)
      } else {
        next.add(sigId)
      }
      return next
    })
  }

  // Historical Telemetry Export Handler
  const handleExport = async (format: 'csv' | 'json') => {
    setExportLoading(format)
    setExportSuccessMsg(null)
    try {
      const { start, end } = getTimeRangeBounds()
      const res = await apiClient.exportTelemetry(machineId, {
        format,
        signal_ids: selectedSignalIds,
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        limit: 25000,
      })

      if (res.error) {
        setError(`Export failed: ${res.error}`)
        return
      }

      const content =
        format === 'json'
          ? JSON.stringify(res.data, null, 2)
          : typeof res.data === 'string'
          ? res.data
          : JSON.stringify(res.data)

      const mimeType = format === 'json' ? 'application/json' : 'text/csv;charset=utf-8;'
      const blob = new Blob([content], { type: mimeType })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = res.filename || `telemetry_${machineId}_${Date.now()}.${format}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)

      setExportSuccessMsg(`Successfully exported ${format.toUpperCase()} telemetry file.`)
      setTimeout(() => setExportSuccessMsg(null), 4000)
    } catch (err: any) {
      setError(err.message || 'Export failed')
    } finally {
      setExportLoading(null)
    }
  }

  // Open Threshold Config Modal
  const openThresholdModal = (reading: SignalReadingItem, e: React.MouseEvent) => {
    e.stopPropagation()
    const thresh = thresholds[reading.signal_id]
    setConfigModalSignal(reading)
    setModalWarnMin(thresh?.warning_min !== undefined && thresh?.warning_min !== null ? String(thresh.warning_min) : '')
    setModalWarnMax(thresh?.warning_max !== undefined && thresh?.warning_max !== null ? String(thresh.warning_max) : '')
    setModalCritMin(thresh?.critical_min !== undefined && thresh?.critical_min !== null ? String(thresh.critical_min) : '')
    setModalCritMax(thresh?.critical_max !== undefined && thresh?.critical_max !== null ? String(thresh.critical_max) : '')
    setModalNotes(thresh?.notes || '')
    setModalError(null)
  }

  // Save Signal Thresholds
  const handleSaveThreshold = async () => {
    if (!configModalSignal) return
    setModalSaving(true)
    setModalError(null)

    try {
      const payload = {
        warning_min: modalWarnMin.trim() !== '' ? parseFloat(modalWarnMin) : null,
        warning_max: modalWarnMax.trim() !== '' ? parseFloat(modalWarnMax) : null,
        critical_min: modalCritMin.trim() !== '' ? parseFloat(modalCritMin) : null,
        critical_max: modalCritMax.trim() !== '' ? parseFloat(modalCritMax) : null,
        unit: configModalSignal.normalized_unit || configModalSignal.source_unit || null,
        notes: modalNotes.trim() || null,
        is_active: true,
      }

      const res = await apiClient.setSignalThreshold(machineId, configModalSignal.signal_id, payload)
      if (res.data) {
        await fetchThresholds()
        await fetchHistory()
        setConfigModalSignal(null)
      } else {
        setModalError(res.error || 'Failed to save threshold.')
      }
    } catch (err: any) {
      setModalError(err.message || 'Error saving threshold')
    } finally {
      setModalSaving(false)
    }
  }

  // Color mapping helper
  const getSignalColor = (sigId: string) => {
    const idx = readings.findIndex((r) => r.signal_id === sigId)
    if (idx >= 0) return SIGNAL_COLORS[idx % SIGNAL_COLORS.length]
    return SIGNAL_COLORS[0]
  }

  // Check if selected signals have multiple differing units
  const hasMultipleUnits = useMemo(() => {
    const selectedUnits = new Set(
      readings
        .filter((r) => selectedSignalIds.includes(r.signal_id))
        .map((r) => r.normalized_unit || r.source_unit || 'dimensionless')
    )
    return selectedUnits.size > 1
  }, [readings, selectedSignalIds])

  // Multi-Signal Chart Data Processing
  const processedSeries = useMemo(() => {
    const visibleIds = selectedSignalIds.filter((id) => !hiddenSignalIds.has(id))
    if (visibleIds.length === 0 || history.length === 0) return []

    return visibleIds.map((sigId) => {
      const sigReadings = history
        .filter(
          (h) =>
            h.signal_id === sigId &&
            h.normalized_value !== null &&
            h.normalized_value !== undefined
        )
        .sort((a, b) => {
          const tA = new Date(a.source_timestamp || 0).getTime()
          const tB = new Date(b.source_timestamp || 0).getTime()
          return tA - tB
        })

      const sigMeta = readings.find((r) => r.signal_id === sigId)
      const unit = sigMeta?.normalized_unit || sigMeta?.source_unit || ''
      const name = sigMeta?.signal_name || sigId

      const values = sigReadings.map((r) => Number(r.normalized_value))
      const min = values.length > 0 ? Math.min(...values) : 0
      const max = values.length > 0 ? Math.max(...values) : 1
      const avg = values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : 0

      const thresh = thresholds[sigId]

      return {
        signalId: sigId,
        name,
        unit,
        color: getSignalColor(sigId),
        readings: sigReadings,
        min,
        max,
        avg,
        threshold: thresh,
      }
    })
  }, [selectedSignalIds, hiddenSignalIds, history, readings, thresholds])

  // Compute Global Time Bounds for Chart X Axis
  const chartTimeRange = useMemo(() => {
    if (history.length === 0) {
      const { start, end } = getTimeRangeBounds()
      return { minT: start.getTime(), maxT: end.getTime(), span: end.getTime() - start.getTime() || 1 }
    }
    const timestamps = history
      .map((h) => new Date(h.source_timestamp || 0).getTime())
      .filter((t) => !isNaN(t) && t > 0)

    if (timestamps.length === 0) {
      const { start, end } = getTimeRangeBounds()
      return { minT: start.getTime(), maxT: end.getTime(), span: end.getTime() - start.getTime() || 1 }
    }

    const minT = Math.min(...timestamps)
    const maxT = Math.max(...timestamps)
    return { minT, maxT, span: maxT - minT || 1 }
  }, [history, getTimeRangeBounds])

  // Visual Badges
  const getObservedStateBadge = (state?: MonitoringState) => {
    switch (state) {
      case 'ACTIVE':
        return {
          bg: 'bg-emerald-50 text-emerald-700 border-emerald-200',
          dot: 'bg-emerald-500 animate-pulse',
          label: 'Continuous Monitoring Active',
        }
      case 'ACTIVATING':
        return {
          bg: 'bg-blue-50 text-[#1685ff] border-blue-200',
          dot: 'bg-[#1685ff] animate-ping',
          label: 'Subscribing to OPC UA Tags...',
        }
      case 'DEGRADED':
        return {
          bg: 'bg-amber-50 text-amber-700 border-amber-200',
          dot: 'bg-amber-500',
          label: 'Degraded Monitoring',
        }
      case 'STOPPING':
        return {
          bg: 'bg-slate-50 text-slate-700 border-slate-200',
          dot: 'bg-slate-400',
          label: 'Deactivating Pipeline...',
        }
      case 'ERROR':
        return {
          bg: 'bg-rose-50 text-rose-700 border-rose-200',
          dot: 'bg-rose-500',
          label: 'Subscription / Gateway Error',
        }
      default:
        return {
          bg: 'bg-slate-100 text-slate-700 border-slate-200',
          dot: 'bg-slate-400',
          label: 'Monitoring Stopped',
        }
    }
  }

  const getFreshnessBadge = (freshness: SignalFreshness) => {
    switch (freshness) {
      case 'FRESH':
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
            <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
            FRESH
          </span>
        )
      case 'DELAYED':
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-[10px] font-bold text-amber-700">
            <span className="size-1.5 rounded-full bg-amber-500" />
            DELAYED
          </span>
        )
      case 'STALE':
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 border border-rose-200 px-2 py-0.5 text-[10px] font-bold text-rose-700">
            <span className="size-1.5 rounded-full bg-rose-500" />
            STALE
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 border border-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
            UNAVAILABLE
          </span>
        )
    }
  }

  const stateInfo = getObservedStateBadge(status?.observed_state)
  const isRunning = status?.observed_state === 'ACTIVE' || status?.observed_state === 'DEGRADED'

  return (
    <div className="space-y-6">
      {/* Top Banner & Control Bar */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <div className="flex size-12 items-center justify-center rounded-xl bg-blue-50 text-[#1685ff]">
              <Activity className="size-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-[#102c50]">Live Continuous Telemetry</h2>
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${stateInfo.bg}`}
                >
                  <span className={`size-2 rounded-full ${stateInfo.dot}`} />
                  {stateInfo.label}
                </span>
              </div>
              <p className="text-xs text-slate-500">
                Asset: <span className="font-semibold text-slate-700">{machineName}</span> ({machineId}) · Neon PostgreSQL Telemetry Stream
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => fetchLiveData(false)}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
              title="Refresh telemetry"
            >
              <RefreshCw className={`size-3.5 text-slate-500 ${loading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>

            <button
              onClick={() => setAutoPoll(!autoPoll)}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-semibold transition ${
                autoPoll
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                  : 'border-slate-200 bg-slate-50 text-slate-600'
              }`}
            >
              <span className={`size-2 rounded-full ${autoPoll ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}`} />
              <span>{autoPoll ? 'Live (2.5s)' : 'Paused'}</span>
            </button>

            {isRunning ? (
              <button
                onClick={handleDeactivate}
                disabled={actionLoading}
                className="inline-flex items-center gap-1.5 rounded-lg border border-rose-300 bg-rose-50 px-4 py-2 text-xs font-bold text-rose-700 shadow-sm transition hover:bg-rose-100 disabled:opacity-50"
              >
                <Square className="size-3.5 fill-rose-700" />
                <span>{actionLoading ? 'Stopping...' : 'Deactivate Monitoring'}</span>
              </button>
            ) : (
              <button
                onClick={handleActivate}
                disabled={actionLoading || (status !== null && !status.can_activate)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[#1685ff] px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-[#126bd0] disabled:opacity-50"
              >
                <Play className="size-3.5 fill-white" />
                <span>{actionLoading ? 'Activating...' : 'Activate Monitoring'}</span>
              </button>
            )}
          </div>
        </div>

        {/* Precondition Notice */}
        {status && !status.can_activate && !isRunning && (
          <div className="mt-4 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50/60 p-4 text-xs text-amber-900">
            <AlertTriangle className="size-4 shrink-0 text-amber-600 mt-0.5" />
            <div className="space-y-1">
              <p className="font-semibold">Activation Preconditions Unmet</p>
              <p className="text-amber-800">{status.activation_precondition_reason}</p>
              {onSwitchToMapping && (
                <button
                  onClick={onSwitchToMapping}
                  className="inline-flex items-center gap-1 pt-1 font-bold text-[#1685ff] hover:underline"
                >
                  <Sliders className="size-3" />
                  <span>Configure Signal Mappings &rarr;</span>
                </button>
              )}
            </div>
          </div>
        )}

        {/* Status Error Banner */}
        {error && (
          <div className="mt-4 flex items-center justify-between gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-medium text-rose-800">
            <div className="flex items-center gap-2">
              <AlertTriangle className="size-4 text-rose-600" />
              <span>{error}</span>
            </div>
            <button onClick={() => setError(null)} className="text-rose-500 hover:text-rose-700">
              <X className="size-4" />
            </button>
          </div>
        )}

        {/* Export Success Banner */}
        {exportSuccessMsg && (
          <div className="mt-4 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-medium text-emerald-800">
            <CheckCircle2 className="size-4 text-emerald-600" />
            <span>{exportSuccessMsg}</span>
          </div>
        )}

        {/* Pipeline Health Bar */}
        <div className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 sm:grid-cols-4">
          <div className="flex items-center gap-2">
            <Radio className="size-4 text-[#1685ff]" />
            <div>
              <p className="text-[10px] font-semibold text-slate-400">ACTIVE SUBSCRIPTIONS</p>
              <p className="text-xs font-bold text-slate-800">
                {status?.active_subscriptions ?? 0} / {status?.total_mapped_signals ?? 0} signals
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Database className="size-4 text-indigo-500" />
            <div>
              <p className="text-[10px] font-semibold text-slate-400">GATEWAY BUFFER QUEUE</p>
              <p className="text-xs font-bold text-slate-800">
                {status?.buffer_metrics?.queue_depth ?? 0} readings queued
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Server className="size-4 text-emerald-500" />
            <div>
              <p className="text-[10px] font-semibold text-slate-400">BUFFERED / DROPPED</p>
              <p className="text-xs font-bold text-slate-800">
                {status?.buffer_metrics?.buffered_readings ?? 0} disk / {status?.buffer_metrics?.dropped_readings ?? 0} lost
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Clock className="size-4 text-slate-400" />
            <div>
              <p className="text-[10px] font-semibold text-slate-400">LAST TELEMETRY UPDATE</p>
              <p className="text-xs font-mono font-medium text-slate-700">
                {lastRefreshed.toLocaleTimeString()}
              </p>
            </div>
          </div>
        </div>

        {/* Endpoint Override Toggle */}
        <div className="mt-3 border-t border-slate-100 pt-3">
          <button
            onClick={() => setShowConfig(!showConfig)}
            className="text-[11px] font-semibold text-slate-500 hover:text-slate-800 flex items-center gap-1"
          >
            <span>{showConfig ? 'Hide' : 'Configure'} OPC UA Gateway Endpoint</span>
            <span className="text-slate-400">({endpointUrl})</span>
          </button>
          {showConfig && (
            <div className="mt-2 flex gap-2">
              <input
                type="text"
                value={endpointUrl}
                onChange={(e) => setEndpointUrl(e.target.value)}
                placeholder="opc.tcp://127.0.0.1:48401/pharmapredict/server/"
                className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-xs text-slate-800"
              />
              <span className="rounded-lg bg-slate-100 px-2.5 py-1.5 text-[11px] font-semibold text-slate-600">
                Read-Only Safe
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Live Sensor Telemetry Cards Grid */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-[#102c50]">Live Sensor Telemetry</h3>
            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-bold text-[#1685ff]">
              {readings.length} {readings.length === 1 ? 'sensor' : 'sensors'}
            </span>
            <span className="text-xs text-slate-400">
              (Click to toggle multi-signal chart inclusion)
            </span>
          </div>
          <span className="text-xs text-slate-400 flex items-center gap-1">
            <ShieldCheck className="size-3.5 text-emerald-500" />
            Strict Read-Only Execution
          </span>
        </div>

        {readings.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
            <Activity className="mx-auto size-8 text-slate-400" />
            <p className="mt-2 text-sm font-bold text-slate-700">No Mapped Signals Found</p>
            <p className="mt-1 text-xs text-slate-500 max-w-md mx-auto">
              Please register OPC UA tags and configure standard signal mappings before activating continuous monitoring.
            </p>
            {onSwitchToMapping && (
              <button
                onClick={onSwitchToMapping}
                className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[#1685ff] px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-[#126bd0]"
              >
                <Sliders className="size-3.5" />
                <span>Go to Signals & Mapping</span>
              </button>
            )}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {readings.map((reading) => {
              const isSelected = selectedSignalIds.includes(reading.signal_id)
              const color = getSignalColor(reading.signal_id)
              const thresh = thresholds[reading.signal_id]

              const displayVal =
                reading.normalized_value !== null && reading.normalized_value !== undefined
                  ? reading.normalized_value.toFixed(2)
                  : reading.source_value !== null && reading.source_value !== undefined
                  ? String(reading.source_value)
                  : '--'

              const breachStatus = reading.threshold_status || 'UNCONFIGURED'

              return (
                <div
                  key={reading.signal_id}
                  onClick={() => toggleSignalSelection(reading.signal_id)}
                  style={{ borderLeftColor: isSelected ? color : 'transparent', borderLeftWidth: isSelected ? '4px' : '1px' }}
                  className={`cursor-pointer rounded-2xl border p-4 transition shadow-sm hover:shadow-md ${
                    isSelected
                      ? 'border-slate-300 bg-blue-50/20 ring-1 ring-blue-100'
                      : 'border-slate-200 bg-white hover:border-slate-300'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      <div
                        className="size-2.5 rounded-full"
                        style={{ backgroundColor: color }}
                        title="Signal overlay color"
                      />
                      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                        {reading.signal_group || 'Sensor'}
                      </span>
                    </div>
                    {getFreshnessBadge(reading.freshness)}
                  </div>

                  <div className="mt-1 flex items-center justify-between">
                    <p className="font-bold text-slate-800 text-sm truncate mr-2" title={reading.signal_name}>
                      {reading.signal_name || 'Signal'}
                    </p>
                    <button
                      onClick={(e) => openThresholdModal(reading, e)}
                      title="Configure operational thresholds"
                      className="text-slate-400 hover:text-slate-700 transition"
                    >
                      <Settings className="size-3.5" />
                    </button>
                  </div>

                  {/* Telemetry Value & Threshold Status Tag */}
                  <div className="mt-3 flex items-baseline justify-between">
                    <div className="flex items-baseline gap-1.5">
                      <span className="font-mono text-2xl font-black text-[#102c50] tracking-tight">
                        {displayVal}
                      </span>
                      <span className="text-xs font-semibold text-slate-500">
                        {reading.normalized_unit || reading.source_unit || ''}
                      </span>
                    </div>

                    {breachStatus === 'CRITICAL' && (
                      <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-black text-rose-700 animate-pulse">
                        CRITICAL
                      </span>
                    )}
                    {breachStatus === 'WARNING' && (
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-black text-amber-700">
                        WARNING
                      </span>
                    )}
                  </div>

                  {/* Threshold Envelope Info */}
                  <div className="mt-2 text-[10px] text-slate-500">
                    {thresh && thresh.configured ? (
                      <div className="flex items-center gap-1 truncate text-slate-600">
                        <span className="font-semibold">Limits:</span>
                        {thresh.warning_min !== null && thresh.warning_max !== null ? (
                          <span>W:[{thresh.warning_min}..{thresh.warning_max}]</span>
                        ) : null}
                        {thresh.critical_max !== null ? (
                          <span className="text-rose-600 font-semibold">C:&gt;{thresh.critical_max}</span>
                        ) : null}
                      </div>
                    ) : (
                      <span className="text-slate-400 italic">No threshold configured</span>
                    )}
                  </div>

                  {/* Metadata Row */}
                  <div className="mt-3 pt-3 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
                    <span className="font-mono truncate max-w-[120px]" title={reading.source_node_id}>
                      {reading.source_node_id || 'Tag'}
                    </span>
                    {reading.quality_code === 'Good' || !reading.quality_code ? (
                      <span className="inline-flex items-center gap-1 font-semibold text-emerald-600">
                        <CheckCircle2 className="size-3" />
                        Good
                      </span>
                    ) : reading.quality_code === 'Bad' ? (
                      <span className="inline-flex items-center gap-1 font-semibold text-rose-600">
                        <AlertTriangle className="size-3 text-rose-500" />
                        Bad
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 font-semibold text-amber-600">
                        <AlertCircle className="size-3 text-amber-500" />
                        {reading.quality_code}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Historical Telemetry & Advanced Multi-Signal Overlay Chart */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
          <div className="flex items-center gap-2">
            <TrendingUp className="size-5 text-[#1685ff]" />
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-[#102c50]">
                  Multi-Signal Telemetry Overlay &amp; Historical Trending
                </h3>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-600">
                  {selectedSignalIds.length} Signals Selected
                </span>
                {chartLoading && (
                  <RefreshCw className="size-3.5 animate-spin text-[#1685ff]" />
                )}
              </div>
              <p className="text-xs text-slate-500">
                Phase 3 Historical Downsampling Engine · Zero Truncation · Full Time-Range Coverage
              </p>
            </div>
          </div>

          {/* Time Window Buttons & Custom Selector */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
              {(['15m', '1h', '6h', '24h', 'custom'] as const).map((w) => (
                <button
                  key={w}
                  onClick={() => setTimeWindow(w)}
                  className={`rounded-md px-2.5 py-1 text-xs font-bold transition ${
                    timeWindow === w
                      ? 'bg-white text-[#1685ff] shadow-sm'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {w === 'custom' ? 'CUSTOM' : w.toUpperCase()}
                </button>
              ))}
            </div>

            {/* Export Telemetry Controls */}
            <div className="flex items-center gap-1">
              <button
                onClick={() => handleExport('csv')}
                disabled={exportLoading !== null || history.length === 0}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
                title="Export filtered historical readings to CSV"
              >
                <Download className="size-3" />
                <span>{exportLoading === 'csv' ? 'Exporting...' : 'Export CSV'}</span>
              </button>
              <button
                onClick={() => handleExport('json')}
                disabled={exportLoading !== null || history.length === 0}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
                title="Export filtered historical readings to JSON"
              >
                <Download className="size-3" />
                <span>{exportLoading === 'json' ? 'Exporting...' : 'JSON'}</span>
              </button>
            </div>
          </div>
        </div>

        {/* Custom Date Range Picker Accordion */}
        {timeWindow === 'custom' && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs">
            <Calendar className="size-4 text-[#1685ff]" />
            <div className="flex items-center gap-2">
              <label className="font-semibold text-slate-600">Start Time:</label>
              <input
                type="datetime-local"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-800"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="font-semibold text-slate-600">End Time:</label>
              <input
                type="datetime-local"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-800"
              />
            </div>
            <button
              onClick={() => fetchHistory()}
              className="rounded-lg bg-[#1685ff] px-3 py-1 font-bold text-white shadow-sm hover:bg-[#126bd0]"
            >
              Apply Filter
            </button>
          </div>
        )}

        {/* Multi-Signal Legend & Visibility Toggles Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-y border-slate-100 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400 mr-1">
              Active Signals:
            </span>
            {selectedSignalIds.map((sigId) => {
              const sigMeta = readings.find((r) => r.signal_id === sigId)
              const color = getSignalColor(sigId)
              const isHidden = hiddenSignalIds.has(sigId)
              const isFocused = focusedSignalId === sigId

              return (
                <div
                  key={sigId}
                  onClick={() => setFocusedSignalId(isFocused ? null : sigId)}
                  className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium cursor-pointer transition ${
                    isFocused
                      ? 'border-[#1685ff] bg-blue-50/50 shadow-sm'
                      : isHidden
                      ? 'border-slate-200 bg-slate-50 text-slate-400 opacity-60'
                      : 'border-slate-200 bg-white text-slate-800 hover:border-slate-300'
                  }`}
                >
                  <span
                    className="size-2.5 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                  <span className="font-semibold">
                    {sigMeta?.signal_name || sigId}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    ({sigMeta?.normalized_unit || sigMeta?.source_unit || 'unit'})
                  </span>

                  <button
                    onClick={(e) => toggleSignalVisibility(sigId, e)}
                    className="ml-1 text-slate-400 hover:text-slate-700"
                    title={isHidden ? 'Show signal curve' : 'Hide signal curve'}
                  >
                    {isHidden ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
                  </button>
                </div>
              )
            })}
          </div>

          {/* Scale Mode Toggle */}
          <div className="flex items-center gap-2 text-xs">
            {hasMultipleUnits && (
              <span className="text-[11px] text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200 font-medium">
                Multiple engineering units detected
              </span>
            )}
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
              <button
                onClick={() => setScaleMode('relative')}
                className={`rounded px-2 py-1 text-[11px] font-bold transition ${
                  scaleMode === 'relative'
                    ? 'bg-white text-[#1685ff] shadow-xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
                title="Normalize each signal to 0-100% of its min/max range for visual alignment"
              >
                Relative (0–100%)
              </button>
              <button
                onClick={() => setScaleMode('raw')}
                className={`rounded px-2 py-1 text-[11px] font-bold transition ${
                  scaleMode === 'raw'
                    ? 'bg-white text-[#1685ff] shadow-xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
                title="Plot exact raw values directly"
              >
                Engineering Units
              </button>
            </div>
          </div>
        </div>

        {/* Signal Stats Summary Chips */}
        {processedSeries.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {processedSeries.map((s) => (
              <div
                key={s.signalId}
                className="rounded-xl border border-slate-100 bg-slate-50/60 p-3 text-xs space-y-1"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 truncate">
                    <span className="size-2 rounded-full" style={{ backgroundColor: s.color }} />
                    <span className="font-bold text-slate-800 truncate">{s.name}</span>
                  </div>
                  <span className="font-mono text-[11px] font-bold text-slate-500">
                    {s.readings.length} pts
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-1 pt-1 font-mono text-[11px] text-slate-600 border-t border-slate-200/60">
                  <div>
                    <span className="text-[9px] uppercase text-slate-400 block font-sans">Min</span>
                    {s.min.toFixed(1)} {s.unit}
                  </div>
                  <div>
                    <span className="text-[9px] uppercase text-slate-400 block font-sans">Avg</span>
                    {s.avg.toFixed(1)} {s.unit}
                  </div>
                  <div>
                    <span className="text-[9px] uppercase text-slate-400 block font-sans">Max</span>
                    {s.max.toFixed(1)} {s.unit}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* SVG Multi-Signal Trend Chart Canvas */}
        <div className="relative h-72 w-full rounded-xl border border-slate-100 bg-slate-50/50 p-4">
          {processedSeries.length === 0 || history.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <Clock className="size-6 text-slate-400" />
              <p className="mt-2 text-xs font-semibold text-slate-600">
                No historical telemetry points found for selected signals in this time window
              </p>
              <p className="text-[11px] text-slate-400">
                Activate continuous monitoring to begin populating time-series data.
              </p>
            </div>
          ) : (
            <div className="h-full w-full">
              <svg className="h-full w-full overflow-visible" viewBox="0 0 800 240" preserveAspectRatio="none">
                {/* Horizontal Scale Grid Lines */}
                <line x1="0" y1="20" x2="800" y2="20" stroke="#e2e8f0" strokeDasharray="3 3" />
                <line x1="0" y1="75" x2="800" y2="75" stroke="#e2e8f0" strokeDasharray="3 3" />
                <line x1="0" y1="130" x2="800" y2="130" stroke="#e2e8f0" strokeDasharray="3 3" />
                <line x1="0" y1="185" x2="800" y2="185" stroke="#e2e8f0" strokeDasharray="3 3" />
                <line x1="0" y1="220" x2="800" y2="220" stroke="#cbd5e1" strokeWidth="1" />

                {/* Y-Axis Reference Labels (0% to 100% or Range) */}
                <text x="6" y="24" fill="#94a3b8" fontSize="9" fontWeight="bold">
                  {scaleMode === 'relative' ? '100% (High)' : 'Max'}
                </text>
                <text x="6" y="134" fill="#94a3b8" fontSize="9" fontWeight="bold">
                  {scaleMode === 'relative' ? '50% (Mid)' : 'Mid'}
                </text>
                <text x="6" y="216" fill="#94a3b8" fontSize="9" fontWeight="bold">
                  {scaleMode === 'relative' ? '0% (Low)' : 'Min'}
                </text>

                {/* Render Each Signal Series */}
                {processedSeries.map((series) => {
                  const pts = series.readings
                  if (pts.length === 0) return null

                  const isFocused = focusedSignalId === series.signalId
                  const isMuted = focusedSignalId !== null && !isFocused

                  // Min/Max for scaling
                  const effectiveMin = scaleMode === 'relative' ? series.min : Math.min(...processedSeries.map((s) => s.min))
                  const effectiveMax = scaleMode === 'relative' ? series.max : Math.max(...processedSeries.map((s) => s.max))
                  const span = effectiveMax - effectiveMin || 1.0

                  // Threshold lines for focused series or if only 1 series
                  const showThresholdLines = (isFocused || processedSeries.length === 1) && series.threshold?.configured
                  const thresh = series.threshold

                  // Compute coordinates
                  const coords = pts.map((p) => {
                    const t = new Date(p.source_timestamp || 0).getTime()
                    const xNorm = (t - chartTimeRange.minT) / chartTimeRange.span
                    const x = Math.max(10, Math.min(790, xNorm * 780 + 10))

                    const val = Number(p.normalized_value)
                    const valNorm = (val - effectiveMin) / span
                    const y = 210 - Math.max(0, Math.min(1, valNorm)) * 180

                    return { x, y, val, time: p.source_timestamp, status: p.threshold_status }
                  })

                  const lineD = coords.reduce((acc, curr, i) => {
                    return i === 0 ? `M ${curr.x} ${curr.y}` : `${acc} L ${curr.x} ${curr.y}`
                  }, '')

                  // Threshold Y positions if applicable
                  let warnY: number | null = null
                  let critY: number | null = null
                  if (showThresholdLines && thresh) {
                    if (thresh.warning_max !== null && thresh.warning_max !== undefined) {
                      const wNorm = (thresh.warning_max - effectiveMin) / span
                      warnY = 210 - Math.max(0, Math.min(1, wNorm)) * 180
                    }
                    if (thresh.critical_max !== null && thresh.critical_max !== undefined) {
                      const cNorm = (thresh.critical_max - effectiveMin) / span
                      critY = 210 - Math.max(0, Math.min(1, cNorm)) * 180
                    }
                  }

                  return (
                    <g key={series.signalId} opacity={isMuted ? 0.25 : 1.0}>
                      {/* Optional Threshold Lines for Focused/Single Signal */}
                      {warnY !== null && (
                        <g>
                          <line
                            x1="0"
                            y1={warnY}
                            x2="800"
                            y2={warnY}
                            stroke="#f59e0b"
                            strokeWidth="1.5"
                            strokeDasharray="4 4"
                          />
                          <text x="730" y={warnY - 4} fill="#f59e0b" fontSize="8" fontWeight="bold">
                            WARN ({thresh?.warning_max} {series.unit})
                          </text>
                        </g>
                      )}
                      {critY !== null && (
                        <g>
                          <line
                            x1="0"
                            y1={critY}
                            x2="800"
                            y2={critY}
                            stroke="#ef4444"
                            strokeWidth="1.5"
                            strokeDasharray="4 4"
                          />
                          <text x="730" y={critY - 4} fill="#ef4444" fontSize="8" fontWeight="bold">
                            CRIT ({thresh?.critical_max} {series.unit})
                          </text>
                        </g>
                      )}

                      {/* Continuous Signal Path */}
                      <path
                        d={lineD}
                        fill="none"
                        stroke={series.color}
                        strokeWidth={isFocused ? '3.5' : '2'}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />

                      {/* Point Markers with Threshold Breach Coloring */}
                      {coords.length <= 60 &&
                        coords.map((c, i) => {
                          const isCrit = c.status === 'CRITICAL'
                          const isWarn = c.status === 'WARNING'
                          const ptColor = isCrit ? '#ef4444' : isWarn ? '#f59e0b' : series.color

                          return (
                            <circle
                              key={i}
                              cx={c.x}
                              cy={c.y}
                              r={isCrit || isWarn ? '4' : '2.5'}
                              fill={isCrit || isWarn ? ptColor : '#ffffff'}
                              stroke={ptColor}
                              strokeWidth={isCrit || isWarn ? '2' : '1.5'}
                            >
                              <title>
                                {series.name}: {c.val.toFixed(2)} {series.unit}
                                &#10;Time: {c.time}
                                {c.status ? `&#10;Status: ${c.status}` : ''}
                              </title>
                            </circle>
                          )
                        })}
                    </g>
                  )
                })}
              </svg>
            </div>
          )}
        </div>
      </div>

      {/* Threshold Configuration Modal */}
      {configModalSignal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="font-bold text-[#102c50]">Configure Operational Thresholds</h3>
                <p className="text-xs text-slate-500">
                  Signal: <span className="font-semibold text-slate-700">{configModalSignal.signal_name}</span> ({configModalSignal.signal_id})
                </p>
              </div>
              <button
                onClick={() => setConfigModalSignal(null)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="size-5" />
              </button>
            </div>

            {modalError && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 p-2.5 text-xs text-rose-800">
                {modalError}
              </div>
            )}

            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-semibold text-slate-600 block mb-1">Warning Lower Limit (Min)</label>
                  <input
                    type="number"
                    step="any"
                    value={modalWarnMin}
                    onChange={(e) => setModalWarnMin(e.target.value)}
                    placeholder="e.g. 20.0"
                    className="w-full rounded-lg border border-slate-300 p-2 font-mono text-xs text-slate-800"
                  />
                </div>
                <div>
                  <label className="font-semibold text-slate-600 block mb-1">Warning Upper Limit (Max)</label>
                  <input
                    type="number"
                    step="any"
                    value={modalWarnMax}
                    onChange={(e) => setModalWarnMax(e.target.value)}
                    placeholder="e.g. 80.0"
                    className="w-full rounded-lg border border-slate-300 p-2 font-mono text-xs text-slate-800"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-semibold text-slate-600 block mb-1">Critical Lower Limit (Min)</label>
                  <input
                    type="number"
                    step="any"
                    value={modalCritMin}
                    onChange={(e) => setModalCritMin(e.target.value)}
                    placeholder="e.g. 10.0"
                    className="w-full rounded-lg border border-slate-300 p-2 font-mono text-xs text-slate-800"
                  />
                </div>
                <div>
                  <label className="font-semibold text-slate-600 block mb-1">Critical Upper Limit (Max)</label>
                  <input
                    type="number"
                    step="any"
                    value={modalCritMax}
                    onChange={(e) => setModalCritMax(e.target.value)}
                    placeholder="e.g. 95.0"
                    className="w-full rounded-lg border border-slate-300 p-2 font-mono text-xs text-slate-800"
                  />
                </div>
              </div>

              <div>
                <label className="font-semibold text-slate-600 block mb-1">Engineering Unit</label>
                <input
                  type="text"
                  disabled
                  value={configModalSignal.normalized_unit || configModalSignal.source_unit || 'dimensionless'}
                  className="w-full rounded-lg border border-slate-200 bg-slate-100 p-2 font-mono text-xs text-slate-600"
                />
              </div>

              <div>
                <label className="font-semibold text-slate-600 block mb-1">Notes / Rationale</label>
                <textarea
                  value={modalNotes}
                  onChange={(e) => setModalNotes(e.target.value)}
                  rows={2}
                  placeholder="e.g. Manufacturer operating limit for motor bearing temperature"
                  className="w-full rounded-lg border border-slate-300 p-2 text-xs text-slate-800"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
              <button
                type="button"
                onClick={() => setConfigModalSignal(null)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveThreshold}
                disabled={modalSaving}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[#1685ff] px-4 py-1.5 text-xs font-bold text-white shadow-sm hover:bg-[#126bd0] disabled:opacity-50"
              >
                <Check className="size-3.5" />
                <span>{modalSaving ? 'Saving...' : 'Save Thresholds'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

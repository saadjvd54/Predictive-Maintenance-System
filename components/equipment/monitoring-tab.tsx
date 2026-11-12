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
  Zap,
} from 'lucide-react'
import {
  apiClient,
  MonitoringStatusResponse,
  SignalReadingItem,
  MonitoringState,
  SignalFreshness,
} from '@/lib/api-client'

interface MonitoringTabProps {
  machineId: string
  machineName: string
  onSwitchToMapping?: () => void
}

export default function MonitoringTab({
  machineId,
  machineName,
  onSwitchToMapping,
}: MonitoringTabProps) {
  const [status, setStatus] = useState<MonitoringStatusResponse | null>(null)
  const [readings, setReadings] = useState<SignalReadingItem[]>([])
  const [history, setHistory] = useState<SignalReadingItem[]>([])
  const [selectedSignalId, setSelectedSignalId] = useState<string>('')
  const [timeWindow, setTimeWindow] = useState<'15m' | '1h' | '6h' | '24h'>('1h')
  const [loading, setLoading] = useState<boolean>(true)
  const [actionLoading, setActionLoading] = useState<boolean>(false)
  const [autoPoll, setAutoPoll] = useState<boolean>(true)
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date())
  const [error, setError] = useState<string | null>(null)
  const [endpointUrl, setEndpointUrl] = useState<string>('opc.tcp://127.0.0.1:48401/pharmapredict/server/')
  const [showConfig, setShowConfig] = useState<boolean>(false)

  const isMounted = useRef<boolean>(true)

  // Fetch status and latest sensor telemetry
  const fetchLiveData = useCallback(async (isInitial = false) => {
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
        setReadings(latestRes.data.readings)
        // Auto-select first signal for chart if none selected
        if (!selectedSignalId && latestRes.data.readings.length > 0) {
          setSelectedSignalId(latestRes.data.readings[0].signal_id)
        }
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
  }, [machineId, selectedSignalId])

  // Fetch historical time series for the selected signal
  const fetchHistory = useCallback(async () => {
    if (!selectedSignalId) return

    const now = new Date()
    let startTime: Date
    switch (timeWindow) {
      case '15m':
        startTime = new Date(now.getTime() - 15 * 60 * 1000)
        break
      case '1h':
        startTime = new Date(now.getTime() - 60 * 60 * 1000)
        break
      case '6h':
        startTime = new Date(now.getTime() - 6 * 60 * 60 * 1000)
        break
      case '24h':
        startTime = new Date(now.getTime() - 24 * 60 * 60 * 1000)
        break
    }

    try {
      const res = await apiClient.getHistoricalReadings(machineId, {
        signal_id: selectedSignalId,
        start_time: startTime.toISOString(),
        end_time: now.toISOString(),
        limit: 300,
      })

      if (isMounted.current && res.data?.readings) {
        setHistory(res.data.readings)
      }
    } catch {
      // Background chart polling error non-fatal
    }
  }, [machineId, selectedSignalId, timeWindow])

  // Mount lifecycle
  useEffect(() => {
    isMounted.current = true
    fetchLiveData(true)

    return () => {
      isMounted.current = false
    }
  }, [fetchLiveData])

  // Chart data fetch when signal or time window changes
  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  // Bounded 2-second live polling interval
  useEffect(() => {
    if (!autoPoll) return

    const intervalId = setInterval(() => {
      fetchLiveData(false)
      if (status?.observed_state === 'ACTIVE' || status?.observed_state === 'DEGRADED') {
        fetchHistory()
      }
    }, 2000)

    return () => clearInterval(intervalId)
  }, [autoPoll, fetchLiveData, fetchHistory, status?.observed_state])

  // Activation Handler
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

  // Deactivation Handler
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

  // Chart Calculations
  const chartData = useMemo(() => {
    const validPoints = history
      .filter((h) => h.normalized_value !== null && h.normalized_value !== undefined)
      .map((h) => ({
        timestamp: new Date(h.source_timestamp || Date.now()),
        value: Number(h.normalized_value),
        unit: h.normalized_unit || '',
      }))

    if (validPoints.length === 0) return null

    const values = validPoints.map((p) => p.value)
    const minVal = Math.min(...values)
    const maxVal = Math.max(...values)
    const avgVal = values.reduce((a, b) => a + b, 0) / values.length

    return {
      points: validPoints,
      min: minVal,
      max: maxVal,
      avg: avgVal,
      unit: validPoints[0]?.unit || '',
    }
  }, [history])

  const stateInfo = getObservedStateBadge(status?.observed_state)
  const isRunning = status?.observed_state === 'ACTIVE' || status?.observed_state === 'DEGRADED'

  return (
    <div className="space-y-6">
      {/* Top Banner: Preconditions & Activation Controls */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-base font-bold text-[#102c50]">
                Continuous OPC UA Data Collection
              </h2>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold ${stateInfo.bg}`}
              >
                <span className={`size-2 rounded-full ${stateInfo.dot}`} />
                {stateInfo.label}
              </span>
              {/* Requirement 12: Clearly distinguish simulator readings from physical PLC readings */}
              {readings.length > 0 && (
                readings[0].simulator_flag !== false ? (
                  <span
                    className="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-800 shadow-xs"
                    title="Data originates from simulated OPC UA machinery. No physical PLC connected."
                  >
                    <Radio className="size-3 text-amber-600 animate-pulse" />
                    Simulated Telemetry (OPC UA Simulator)
                  </span>
                ) : (
                  <span
                    className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300 bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-800 shadow-xs"
                    title="Data originates from live physical PLC / Purdue Level 1/2 control network."
                  >
                    <Server className="size-3 text-emerald-600" />
                    Physical Industrial PLC (Purdue L1/L2)
                  </span>
                )
              )}
            </div>
            <p className="text-xs text-slate-500">
              Live industrial telemetry collection pipeline with TimescaleDB time-series storage and unit normalization.
            </p>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => fetchLiveData(false)}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
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
              <span>{autoPoll ? 'Live (2s)' : 'Paused'}</span>
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

        {/* Precondition Notice if Inactive */}
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

        {/* Status Details / Error Banner */}
        {error && (
          <div className="mt-4 flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-medium text-rose-800">
            <AlertTriangle className="size-4 text-rose-600" />
            <span>{error}</span>
          </div>
        )}

        {/* Pipeline Health Metrics Bar */}
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
              Please register OPC UA tags and configure standard signal mappings in Step 6 before activating monitoring.
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
              const isSelected = selectedSignalId === reading.signal_id
              const displayVal =
                reading.normalized_value !== null && reading.normalized_value !== undefined
                  ? reading.normalized_value.toFixed(2)
                  : reading.source_value !== null && reading.source_value !== undefined
                  ? String(reading.source_value)
                  : '--'

              return (
                <div
                  key={reading.signal_id}
                  onClick={() => setSelectedSignalId(reading.signal_id)}
                  className={`cursor-pointer rounded-2xl border p-4 transition shadow-sm hover:shadow-md ${
                    isSelected
                      ? 'border-[#1685ff] bg-blue-50/30 ring-2 ring-[#1685ff]/20'
                      : 'border-slate-200 bg-white hover:border-slate-300'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      {reading.signal_group || 'Sensor'}
                    </span>
                    {getFreshnessBadge(reading.freshness)}
                  </div>

                  <p className="mt-1 font-bold text-slate-800 text-sm truncate" title={reading.signal_name}>
                    {reading.signal_name || 'Signal'}
                  </p>

                  {/* Big Telemetry Value */}
                  <div className="mt-3 flex items-baseline gap-1.5">
                    <span className="font-mono text-2xl font-black text-[#102c50] tracking-tight">
                      {displayVal}
                    </span>
                    <span className="text-xs font-semibold text-slate-500">
                      {reading.normalized_unit || reading.source_unit || ''}
                    </span>
                  </div>

                  {/* Metadata Row */}
                  <div className="mt-3 pt-3 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
                    <span className="font-mono truncate max-w-[120px]" title={reading.source_node_id}>
                      {reading.source_node_id || 'Tag'}
                    </span>
                    {/* Requirement 3: Clearly display good, bad, or stale/uncertain quality codes */}
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

      {/* Historical Telemetry Trend Chart */}
      {selectedSignalId && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
            <div className="flex items-center gap-2">
              <TrendingUp className="size-5 text-[#1685ff]" />
              <div>
                <h3 className="text-sm font-bold text-[#102c50]">
                  Time-Series Historical Telemetry Trend
                </h3>
                <p className="text-xs text-slate-500">
                  {readings.find((r) => r.signal_id === selectedSignalId)?.signal_name || 'Selected Sensor'} · TimescaleDB Continuous Stream
                </p>
              </div>
            </div>

            {/* Time Window Buttons */}
            <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
              {(['15m', '1h', '6h', '24h'] as const).map((w) => (
                <button
                  key={w}
                  onClick={() => setTimeWindow(w)}
                  className={`rounded-md px-2.5 py-1 text-xs font-bold transition ${
                    timeWindow === w
                      ? 'bg-white text-[#1685ff] shadow-sm'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {w.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Chart Summary Badges */}
          {chartData && (
            <div className="flex flex-wrap items-center gap-4 text-xs">
              <div className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-1.5">
                <span className="text-slate-400 font-semibold mr-1.5">MIN:</span>
                <span className="font-mono font-bold text-slate-700">
                  {chartData.min.toFixed(2)} {chartData.unit}
                </span>
              </div>
              <div className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-1.5">
                <span className="text-slate-400 font-semibold mr-1.5">AVG:</span>
                <span className="font-mono font-bold text-slate-700">
                  {chartData.avg.toFixed(2)} {chartData.unit}
                </span>
              </div>
              <div className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-1.5">
                <span className="text-slate-400 font-semibold mr-1.5">MAX:</span>
                <span className="font-mono font-bold text-slate-700">
                  {chartData.max.toFixed(2)} {chartData.unit}
                </span>
              </div>
              <div className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-1.5">
                <span className="text-slate-400 font-semibold mr-1.5">DATA POINTS:</span>
                <span className="font-mono font-bold text-slate-700">
                  {chartData.points.length} readings
                </span>
              </div>
            </div>
          )}

          {/* SVG Line Chart */}
          <div className="relative h-64 w-full rounded-xl border border-slate-100 bg-slate-50/50 p-4">
            {!chartData || chartData.points.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <Clock className="size-6 text-slate-400" />
                <p className="mt-2 text-xs font-semibold text-slate-600">
                  No historical data points in this window
                </p>
                <p className="text-[11px] text-slate-400">
                  Activate monitoring to begin collecting continuous telemetry.
                </p>
              </div>
            ) : (
              <div className="h-full w-full">
                <svg className="h-full w-full overflow-visible" viewBox="0 0 600 200" preserveAspectRatio="none">
                  {/* Horizontal Grid lines */}
                  <line x1="0" y1="20" x2="600" y2="20" stroke="#e2e8f0" strokeDasharray="3 3" />
                  <line x1="0" y1="70" x2="600" y2="70" stroke="#e2e8f0" strokeDasharray="3 3" />
                  <line x1="0" y1="120" x2="600" y2="120" stroke="#e2e8f0" strokeDasharray="3 3" />
                  <line x1="0" y1="170" x2="600" y2="170" stroke="#e2e8f0" strokeDasharray="3 3" />

                  {/* Gradient Area Definition */}
                  <defs>
                    <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#1685ff" stopOpacity="0.25" />
                      <stop offset="100%" stopColor="#1685ff" stopOpacity="0.0" />
                    </linearGradient>
                  </defs>

                  {/* Compute Path Coordinates */}
                  {(() => {
                    const points = chartData.points
                    const span = chartData.max - chartData.min || 1.0
                    const padding = span * 0.1
                    const effectiveMin = chartData.min - padding
                    const effectiveMax = chartData.max + padding
                    const range = effectiveMax - effectiveMin || 1.0

                    const coords = points.map((p, idx) => {
                      const x = (idx / Math.max(1, points.length - 1)) * 600
                      const normalizedY = (p.value - effectiveMin) / range
                      const y = 180 - normalizedY * 160
                      return { x, y }
                    })

                    const lineD = coords.reduce((acc, curr, i) => {
                      return i === 0 ? `M ${curr.x} ${curr.y}` : `${acc} L ${curr.x} ${curr.y}`
                    }, '')

                    const areaD = `${lineD} L ${coords[coords.length - 1].x} 190 L ${coords[0].x} 190 Z`

                    return (
                      <>
                        <path d={areaD} fill="url(#trendGradient)" />
                        <path d={lineD} fill="none" stroke="#1685ff" strokeWidth="2.5" strokeLinecap="round" />
                        {coords.length <= 30 &&
                          coords.map((c, i) => (
                            <circle key={i} cx={c.x} cy={c.y} r="3" fill="#ffffff" stroke="#1685ff" strokeWidth="2" />
                          ))}
                      </>
                    )
                  })()}
                </svg>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}


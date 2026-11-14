'use client'

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Layers,
  Search,
  Filter,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Play,
  RotateCcw,
  Eye,
  Edit3,
  Check,
  X,
  FileText,
  Clock,
  ShieldCheck,
  Tag,
  Loader2,
  Activity,
  ArrowRight,
  Info,
  UploadCloud,
} from 'lucide-react'
import apiClient, {
  CommissioningSessionItem,
  DiscoveredSignalCandidateItem,
} from '@/lib/api-client'

interface CommissioningReviewPanelProps {
  machineId: string
  machineName?: string
  assetCode?: string
  onActivationSuccess?: () => void
}

const CATEGORIES = [
  'All',
  'Temperature',
  'Vibration',
  'Motor Current',
  'Speed',
  'Pressure',
  'Vacuum',
  'Flow',
  'Alarms',
  'Cycles',
  'Other',
]

const CONFIDENCE_LEVELS = ['ALL', 'HIGH', 'MEDIUM', 'LOW', 'UNMAPPED']

export default function CommissioningReviewPanel({
  machineId,
  machineName = 'Equipment Asset',
  assetCode = 'DEMO-BPK-200',
  onActivationSuccess,
}: CommissioningReviewPanelProps) {
  const [sessions, setSessions] = useState<CommissioningSessionItem[]>([])
  const [activeSession, setActiveSession] = useState<CommissioningSessionItem | null>(null)
  const [candidates, setCandidates] = useState<DiscoveredSignalCandidateItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Filters
  const [activeTab, setActiveTab] = useState<'mapped' | 'unmapped'>('mapped')
  const [selectedCategory, setSelectedCategory] = useState('All')
  const [selectedConfidence, setSelectedConfidence] = useState('ALL')
  const [selectedStatus, setSelectedStatus] = useState('ALL')
  const [searchQuery, setSearchQuery] = useState('')

  // Selection
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(new Set())

  // Modals
  const [editingCandidate, setEditingCandidate] = useState<DiscoveredSignalCandidateItem | null>(null)
  const [editForm, setEditForm] = useState<Partial<DiscoveredSignalCandidateItem>>({})
  const [savingEdit, setSavingEdit] = useState(false)

  const [reviewModalCandidate, setReviewModalCandidate] = useState<DiscoveredSignalCandidateItem | null>(null)
  const [reviewDecision, setReviewDecision] = useState<'APPROVED' | 'REJECTED'>('APPROVED')
  const [reviewReason, setReviewReason] = useState('')
  const [submittingReview, setSubmittingReview] = useState(false)

  const [auditCandidate, setAuditCandidate] = useState<DiscoveredSignalCandidateItem | null>(null)
  const [showSessionAudit, setShowSessionAudit] = useState(false)

  const [importJsonText, setImportJsonText] = useState('')
  const [showImportModal, setShowImportModal] = useState(false)
  const [importing, setImporting] = useState(false)

  const [activating, setActivating] = useState(false)
  const [rollingBack, setRollingBack] = useState(false)

  // Load Sessions
  const loadSessions = useCallback(async () => {
    try {
      const res = await apiClient.getCommissioningSessions(machineId)
      if (res.data?.sessions) {
        setSessions(res.data.sessions)
        if (res.data.sessions.length > 0 && !activeSession) {
          setActiveSession(res.data.sessions[0])
        }
      }
    } catch (err: any) {
      console.error('Failed to load commissioning sessions:', err)
    }
  }, [machineId, activeSession])

  // Load Candidates
  const loadCandidates = useCallback(async () => {
    if (!activeSession) return
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.getSessionCandidates(activeSession.id, {
        category: selectedCategory === 'All' ? undefined : selectedCategory,
        confidence: selectedConfidence === 'ALL' ? undefined : selectedConfidence,
        status: selectedStatus === 'ALL' ? undefined : selectedStatus,
        is_mapped: activeTab === 'mapped',
        search: searchQuery.trim() || undefined,
      })
      if (res.data?.candidates) {
        setCandidates(res.data.candidates)
      } else {
        setCandidates([])
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load candidates.')
    } finally {
      setLoading(false)
    }
  }, [activeSession, selectedCategory, selectedConfidence, selectedStatus, activeTab, searchQuery])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    loadCandidates()
  }, [loadCandidates])

  // Clear success notification after 5s
  useEffect(() => {
    if (successMsg) {
      const t = setTimeout(() => setSuccessMsg(null), 5000)
      return () => clearTimeout(t)
    }
  }, [successMsg])

  // Selection toggle
  const toggleSelect = (id: string) => {
    const next = new Set(selectedCandidateIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedCandidateIds(next)
  }

  const toggleSelectAll = () => {
    if (selectedCandidateIds.size === candidates.length) {
      setSelectedCandidateIds(new Set())
    } else {
      setSelectedCandidateIds(new Set(candidates.map((c) => c.id)))
    }
  }

  // Handle Edit
  const openEditModal = (c: DiscoveredSignalCandidateItem) => {
    setEditingCandidate(c)
    setEditForm({
      suggested_signal_code: c.suggested_signal_code || '',
      custom_name: c.custom_name || '',
      engineering_unit: c.engineering_unit || c.source_unit || '',
      scaling_factor: c.scaling_factor,
      offset: c.offset,
      sampling_interval_ms: c.sampling_interval_ms,
      warning_min: c.warning_min,
      warning_max: c.warning_max,
      critical_min: c.critical_min,
      critical_max: c.critical_max,
    })
  }

  const handleSaveEdit = async () => {
    if (!editingCandidate) return
    setSavingEdit(true)
    setError(null)
    try {
      const res = await apiClient.updateCandidateMapping(editingCandidate.id, editForm)
      if (res.error) {
        setError(res.error)
      } else {
        setSuccessMsg(`Candidate mapping for ${editingCandidate.display_name} updated successfully.`)
        setEditingCandidate(null)
        loadCandidates()
        loadSessions()
      }
    } catch (err: any) {
      setError(err?.message || 'Error updating candidate.')
    } finally {
      setSavingEdit(false)
    }
  }

  // Handle Single Review (Approve/Reject)
  const openReviewModal = (c: DiscoveredSignalCandidateItem, decision: 'APPROVED' | 'REJECTED') => {
    setReviewModalCandidate(c)
    setReviewDecision(decision)
    setReviewReason('')
  }

  const handleSubmitReview = async () => {
    if (!reviewModalCandidate) return
    setSubmittingReview(true)
    setError(null)
    try {
      const res = await apiClient.reviewCandidate(reviewModalCandidate.id, reviewDecision, reviewReason)
      if (res.error) {
        setError(res.error)
      } else {
        setSuccessMsg(`Signal '${reviewModalCandidate.display_name}' ${reviewDecision.toLowerCase()}.`)
        setReviewModalCandidate(null)
        loadCandidates()
        loadSessions()
      }
    } catch (err: any) {
      setError(err?.message || 'Error submitting review decision.')
    } finally {
      setSubmittingReview(false)
    }
  }

  // Handle Bulk Review
  const handleBulkReview = async (decision: 'APPROVED' | 'REJECTED') => {
    if (!activeSession || selectedCandidateIds.size === 0) return
    setLoading(true)
    setError(null)
    try {
      const ids = Array.from(selectedCandidateIds)
      const res = await apiClient.bulkReviewCandidates(
        activeSession.id,
        ids,
        decision,
        `Bulk ${decision.toLowerCase()} by engineer.`
      )
      if (res.error) {
        setError(res.error)
      } else {
        setSuccessMsg(`Bulk updated ${res.data?.result?.updated_count || ids.length} candidate(s) to ${decision}.`)
        setSelectedCandidateIds(new Set())
        loadCandidates()
        loadSessions()
      }
    } catch (err: any) {
      setError(err?.message || 'Bulk review failed.')
    } finally {
      setLoading(false)
    }
  }

  // Handle Activation
  const handleActivate = async () => {
    if (!activeSession) return
    const approvedCount = activeSession.approved_count
    if (approvedCount === 0) {
      setError('Cannot activate: No candidates have been APPROVED. Review and approve signals first.')
      return
    }

    if (!confirm(`Are you sure you want to activate ${approvedCount} approved signal(s) into live production MachineSignal configurations?`)) {
      return
    }

    setActivating(true)
    setError(null)
    try {
      const res = await apiClient.activateCommissioningSession(activeSession.id)
      if (res.error) {
        setError(res.error)
      } else {
        setSuccessMsg(`Session activated! ${res.data?.activation?.activated_count || approvedCount} signal(s) registered in production.`)
        loadSessions()
        loadCandidates()
        if (onActivationSuccess) onActivationSuccess()
      }
    } catch (err: any) {
      setError(err?.message || 'Activation failed.')
    } finally {
      setActivating(false)
    }
  }

  // Handle Rollback
  const handleRollback = async () => {
    if (!activeSession) return
    const reason = prompt('Enter a reason for rolling back this activated commissioning session:')
    if (!reason) return

    setRollingBack(true)
    setError(null)
    try {
      const res = await apiClient.rollbackCommissioningSession(activeSession.id, reason)
      if (res.error) {
        setError(res.error)
      } else {
        setSuccessMsg('Session activation successfully rolled back. Production signals deactivated.')
        loadSessions()
        loadCandidates()
      }
    } catch (err: any) {
      setError(err?.message || 'Rollback failed.')
    } finally {
      setRollingBack(false)
    }
  }

  // Handle Import JSON
  const handleImportJson = async () => {
    if (!importJsonText.trim()) return
    setImporting(true)
    setError(null)
    try {
      const parsed = JSON.parse(importJsonText)
      const res = await apiClient.importCommissioningDiscovery(machineId, parsed)
      if (res.error) {
        setError(res.error)
      } else {
        setSuccessMsg('Discovery output imported successfully into new commissioning session.')
        setShowImportModal(false)
        setImportJsonText('')
        await loadSessions()
        if (res.data?.session) {
          setActiveSession(res.data.session)
        }
      }
    } catch (err: any) {
      setError(err?.message || 'Invalid JSON format or import failure.')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Top Banner / Session Selector */}
      <div className="rounded-xl border border-slate-700/60 bg-slate-850 p-5 shadow-lg">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded bg-sky-500/10 px-2 py-0.5 text-xs font-semibold text-sky-400">
                Phase 9 Industrial Commissioning
              </span>
              <span className="text-xs text-slate-400">&bull;</span>
              <span className="text-xs font-mono text-slate-300">{assetCode}</span>
            </div>
            <h2 className="mt-1 text-xl font-bold text-white">
              Human-Approved Signal Mapping & Review
            </h2>
            <p className="mt-0.5 text-xs text-slate-400">
              Audit discovered OPC UA tags, correct mappings, validate physical engineering units, and approve production activation.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Session Selector */}
            <select
              value={activeSession?.id || ''}
              onChange={(e) => {
                const s = sessions.find((x) => x.id === e.target.value)
                if (s) setActiveSession(s)
              }}
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-medium text-white focus:border-sky-500 focus:outline-none"
            >
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.session_name} ({s.status})
                </option>
              ))}
              {sessions.length === 0 && <option value="">No Active Sessions</option>}
            </select>

            <button
              onClick={() => setShowImportModal(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
            >
              <UploadCloud className="h-3.5 w-3.5 text-sky-400" />
              Import Discovery JSON
            </button>

            {activeSession && (
              <button
                onClick={() => setShowSessionAudit(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
              >
                <FileText className="h-3.5 w-3.5 text-slate-400" />
                Session Audit Log
              </button>
            )}
          </div>
        </div>

        {/* Session Stats Bar */}
        {activeSession && (
          <div className="mt-5 grid grid-cols-2 gap-3 border-t border-slate-750 pt-4 sm:grid-cols-6">
            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Session Status</span>
              <div className="mt-1 flex items-center gap-1.5">
                <span
                  className={`inline-block h-2 w-2 rounded-full ${
                    activeSession.status === 'ACTIVATED'
                      ? 'bg-emerald-400'
                      : activeSession.status === 'APPROVED'
                      ? 'bg-sky-400'
                      : activeSession.status === 'REJECTED'
                      ? 'bg-rose-400'
                      : 'bg-amber-400'
                  }`}
                />
                <span className="text-xs font-bold text-white">{activeSession.status}</span>
              </div>
            </div>

            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Discovered Tags</span>
              <p className="mt-1 text-base font-bold text-white">{activeSession.discovered_nodes_count}</p>
            </div>

            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Mapped Candidates</span>
              <p className="mt-1 text-base font-bold text-sky-400">{activeSession.mapped_candidates_count}</p>
            </div>

            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Approved</span>
              <p className="mt-1 text-base font-bold text-emerald-400">{activeSession.approved_count}</p>
            </div>

            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Rejected</span>
              <p className="mt-1 text-base font-bold text-rose-400">{activeSession.rejected_count}</p>
            </div>

            <div className="rounded-lg bg-slate-900/60 p-2.5">
              <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Activated Signals</span>
              <p className="mt-1 text-base font-bold text-emerald-300">{activeSession.activated_count}</p>
            </div>
          </div>
        )}
      </div>

      {/* Notifications */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto text-rose-300 hover:text-white">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {successMsg && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-xs text-emerald-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg(null)} className="ml-auto text-emerald-300 hover:text-white">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Main Review Section */}
      <div className="rounded-xl border border-slate-700/60 bg-slate-850 p-5 shadow-lg">
        {/* Navigation Tabs (Mapped vs Unmapped) */}
        <div className="flex items-center justify-between border-b border-slate-750 pb-3">
          <div className="flex gap-2">
            <button
              onClick={() => setActiveTab('mapped')}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === 'mapped'
                  ? 'bg-sky-500 text-white shadow-sm'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-750 hover:text-slate-200'
              }`}
            >
              Mapped Candidates ({activeSession?.mapped_candidates_count || 0})
            </button>
            <button
              onClick={() => setActiveTab('unmapped')}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === 'unmapped'
                  ? 'bg-sky-500 text-white shadow-sm'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-750 hover:text-slate-200'
              }`}
            >
              Unmapped Nodes ({activeSession?.unmapped_candidates_count || 0})
            </button>
          </div>

          {/* Action Buttons for Selected Candidates */}
          <div className="flex items-center gap-2">
            {selectedCandidateIds.size > 0 && activeSession?.status !== 'ACTIVATED' && (
              <>
                <button
                  onClick={() => handleBulkReview('APPROVED')}
                  className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow hover:bg-emerald-500"
                >
                  <Check className="h-3.5 w-3.5" />
                  Approve ({selectedCandidateIds.size})
                </button>
                <button
                  onClick={() => handleBulkReview('REJECTED')}
                  className="inline-flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white shadow hover:bg-rose-500"
                >
                  <X className="h-3.5 w-3.5" />
                  Reject ({selectedCandidateIds.size})
                </button>
              </>
            )}

            {activeSession && activeSession.status !== 'ACTIVATED' && (
              <button
                onClick={handleActivate}
                disabled={activating || activeSession.approved_count === 0}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold text-white shadow transition ${
                  activeSession.approved_count > 0 && !activating
                    ? 'bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500'
                    : 'cursor-not-allowed bg-slate-750 text-slate-500'
                }`}
              >
                {activating ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5 fill-current" />
                )}
                Activate Approved ({activeSession.approved_count})
              </button>
            )}

            {activeSession && activeSession.status === 'ACTIVATED' && (
              <button
                onClick={handleRollback}
                disabled={rollingBack}
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-300 hover:bg-amber-500/20"
              >
                {rollingBack ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RotateCcw className="h-3.5 w-3.5" />
                )}
                Rollback Activation
              </button>
            )}
          </div>
        </div>

        {/* Filters Toolbar */}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {/* Search Input */}
          <div className="relative min-w-[220px] flex-1">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-500" />
            <input
              type="text"
              placeholder="Search by NodeId, name, or code..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-900 py-1.5 pl-8 pr-3 text-xs text-white placeholder-slate-500 focus:border-sky-500 focus:outline-none"
            />
          </div>

          {/* Category Dropdown */}
          <div className="flex items-center gap-1 text-xs text-slate-400">
            <Filter className="h-3.5 w-3.5" />
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-200 focus:border-sky-500 focus:outline-none"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  Category: {c}
                </option>
              ))}
            </select>
          </div>

          {/* Confidence Dropdown */}
          <select
            value={selectedConfidence}
            onChange={(e) => setSelectedConfidence(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-200 focus:border-sky-500 focus:outline-none"
          >
            {CONFIDENCE_LEVELS.map((cl) => (
              <option key={cl} value={cl}>
                Confidence: {cl}
              </option>
            ))}
          </select>

          {/* Status Dropdown */}
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-200 focus:border-sky-500 focus:outline-none"
          >
            <option value="ALL">Status: All</option>
            <option value="PENDING_REVIEW">PENDING_REVIEW</option>
            <option value="APPROVED">APPROVED</option>
            <option value="REJECTED">REJECTED</option>
            <option value="ACTIVATED">ACTIVATED</option>
          </select>
        </div>

        {/* Candidate Signals Table */}
        <div className="mt-4 overflow-x-auto rounded-lg border border-slate-750">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-900/90 uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-3 py-3 w-8">
                  <input
                    type="checkbox"
                    checked={candidates.length > 0 && selectedCandidateIds.size === candidates.length}
                    onChange={toggleSelectAll}
                    className="rounded border-slate-700 bg-slate-900 text-sky-500"
                  />
                </th>
                <th className="px-3 py-3">Source Node / Display Name</th>
                <th className="px-3 py-3">Category</th>
                <th className="px-3 py-3">DataType / Unit</th>
                <th className="px-3 py-3">Suggested Code / Mapping</th>
                <th className="px-3 py-3">Confidence</th>
                <th className="px-3 py-3">Validation</th>
                <th className="px-3 py-3">Status</th>
                <th className="px-3 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80 bg-slate-850/50 text-slate-300">
              {loading ? (
                <tr>
                  <td colSpan={9} className="py-10 text-center text-slate-400">
                    <Loader2 className="mx-auto h-6 w-6 animate-spin text-sky-400" />
                    <span className="mt-2 block text-xs">Loading candidates...</span>
                  </td>
                </tr>
              ) : candidates.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-500">
                    No candidates found matching the selected filters.
                  </td>
                </tr>
              ) : (
                candidates.map((c) => {
                  const isChecked = selectedCandidateIds.has(c.id)
                  return (
                    <tr
                      key={c.id}
                      className={`hover:bg-slate-800/60 transition ${
                        isChecked ? 'bg-sky-500/5' : ''
                      }`}
                    >
                      <td className="px-3 py-3">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleSelect(c.id)}
                          className="rounded border-slate-700 bg-slate-900 text-sky-500"
                        />
                      </td>

                      {/* Source Node */}
                      <td className="px-3 py-3 font-medium text-white max-w-[220px]">
                        <div className="font-semibold text-slate-100 truncate" title={c.display_name || c.browse_name || ''}>
                          {c.display_name || c.browse_name}
                        </div>
                        <div className="font-mono text-[10px] text-slate-500 truncate" title={c.source_node_id}>
                          {c.source_node_id}
                        </div>
                      </td>

                      {/* Category */}
                      <td className="px-3 py-3 text-slate-300">
                        <span className="rounded bg-slate-800 px-2 py-0.5 text-[11px] text-slate-300">
                          {c.suggested_category || 'Other'}
                        </span>
                      </td>

                      {/* Data Type & Unit */}
                      <td className="px-3 py-3 text-slate-300">
                        <div>
                          <span className="font-mono text-[11px] text-slate-400">{c.source_data_type || 'Unknown'}</span>
                          {c.engineering_unit && (
                            <span className="ml-1.5 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-semibold text-sky-400">
                              {c.engineering_unit}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Suggested Mapping */}
                      <td className="px-3 py-3">
                        {c.suggested_signal_code ? (
                          <div className="flex flex-col">
                            <span className="font-mono text-xs font-semibold text-sky-400">
                              {c.suggested_signal_code}
                            </span>
                            {c.custom_name && (
                              <span className="text-[10px] text-slate-400 truncate">{c.custom_name}</span>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-500 italic">Unassigned</span>
                        )}
                      </td>

                      {/* Confidence */}
                      <td className="px-3 py-3">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            c.confidence_level === 'HIGH'
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : c.confidence_level === 'MEDIUM'
                              ? 'bg-sky-500/10 text-sky-400 border border-sky-500/20'
                              : c.confidence_level === 'LOW'
                              ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                              : 'bg-slate-700/50 text-slate-400'
                          }`}
                        >
                          {c.confidence_level} ({(c.confidence_score * 100).toFixed(0)}%)
                        </span>
                      </td>

                      {/* Validation */}
                      <td className="px-3 py-3">
                        {c.validation_errors && c.validation_errors.length > 0 ? (
                          <span
                            className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-400"
                            title={c.validation_errors.join('; ')}
                          >
                            <XCircle className="h-3.5 w-3.5 shrink-0" />
                            {c.validation_errors.length} error(s)
                          </span>
                        ) : c.validation_warnings && c.validation_warnings.length > 0 ? (
                          <span
                            className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-400"
                            title={c.validation_warnings.join('; ')}
                          >
                            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                            Warning
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-400">
                            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                            Valid
                          </span>
                        )}
                      </td>

                      {/* Status */}
                      <td className="px-3 py-3">
                        <span
                          className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                            c.status === 'APPROVED'
                              ? 'bg-emerald-500/10 text-emerald-400'
                              : c.status === 'ACTIVATED'
                              ? 'bg-indigo-500/10 text-indigo-400 font-bold border border-indigo-500/20'
                              : c.status === 'REJECTED'
                              ? 'bg-rose-500/10 text-rose-400'
                              : 'bg-amber-500/10 text-amber-400'
                          }`}
                        >
                          {c.status}
                        </span>
                      </td>

                      {/* Actions */}
                      <td className="px-3 py-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {/* Edit mapping */}
                          <button
                            onClick={() => openEditModal(c)}
                            title="Edit / Correct Mapping"
                            className="rounded p-1 text-slate-400 hover:bg-slate-750 hover:text-white"
                          >
                            <Edit3 className="h-3.5 w-3.5" />
                          </button>

                          {/* Quick Approve */}
                          {c.status !== 'APPROVED' && c.status !== 'ACTIVATED' && (
                            <button
                              onClick={() => openReviewModal(c, 'APPROVED')}
                              title="Approve Mapping"
                              className="rounded p-1 text-emerald-400 hover:bg-emerald-500/20"
                            >
                              <Check className="h-3.5 w-3.5" />
                            </button>
                          )}

                          {/* Quick Reject */}
                          {c.status !== 'REJECTED' && c.status !== 'ACTIVATED' && (
                            <button
                              onClick={() => openReviewModal(c, 'REJECTED')}
                              title="Reject Mapping"
                              className="rounded p-1 text-rose-400 hover:bg-rose-500/20"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          )}

                          {/* Audit History */}
                          <button
                            onClick={() => setAuditCandidate(c)}
                            title="Inspect Audit History"
                            className="rounded p-1 text-slate-400 hover:bg-slate-750 hover:text-white"
                          >
                            <Clock className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* MODAL 1: Edit Mapping */}
      {editingCandidate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-850 p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-750 pb-3">
              <h3 className="text-base font-bold text-white">Manual Mapping Correction</h3>
              <button
                onClick={() => setEditingCandidate(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 space-y-3.5 text-xs">
              <div>
                <span className="font-semibold text-slate-400">Source OPC UA Node:</span>
                <p className="mt-0.5 font-mono text-[11px] text-sky-400 break-all">
                  {editingCandidate.source_node_id}
                </p>
              </div>

              <div>
                <label className="block font-semibold text-slate-300">Canonical Signal Code</label>
                <input
                  type="text"
                  value={editForm.suggested_signal_code || ''}
                  onChange={(e) => setEditForm({ ...editForm, suggested_signal_code: e.target.value })}
                  placeholder="e.g. SEALING_TEMP, MOTOR_VIBRATION"
                  className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-white uppercase font-mono focus:border-sky-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-300">Custom Signal Name</label>
                <input
                  type="text"
                  value={editForm.custom_name || ''}
                  onChange={(e) => setEditForm({ ...editForm, custom_name: e.target.value })}
                  placeholder="e.g. Primary Sealing Jaw Temperature"
                  className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-white focus:border-sky-500 focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-300">Engineering Unit</label>
                  <input
                    type="text"
                    value={editForm.engineering_unit || ''}
                    onChange={(e) => setEditForm({ ...editForm, engineering_unit: e.target.value })}
                    placeholder="°C, mm/s, bar, RPM"
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-white focus:border-sky-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-300">Sampling Rate (ms)</label>
                  <input
                    type="number"
                    value={editForm.sampling_interval_ms || 1000}
                    onChange={(e) => setEditForm({ ...editForm, sampling_interval_ms: Number(e.target.value) })}
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-white focus:border-sky-500 focus:outline-none"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-300">Warning Min / Max</label>
                  <div className="mt-1 flex gap-2">
                    <input
                      type="number"
                      placeholder="Min"
                      value={editForm.warning_min ?? ''}
                      onChange={(e) =>
                        setEditForm({
                          ...editForm,
                          warning_min: e.target.value === '' ? null : Number(e.target.value),
                        })
                      }
                      className="w-1/2 rounded border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white"
                    />
                    <input
                      type="number"
                      placeholder="Max"
                      value={editForm.warning_max ?? ''}
                      onChange={(e) =>
                        setEditForm({
                          ...editForm,
                          warning_max: e.target.value === '' ? null : Number(e.target.value),
                        })
                      }
                      className="w-1/2 rounded border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white"
                    />
                  </div>
                </div>

                <div>
                  <label className="block font-semibold text-slate-300">Critical Min / Max</label>
                  <div className="mt-1 flex gap-2">
                    <input
                      type="number"
                      placeholder="Min"
                      value={editForm.critical_min ?? ''}
                      onChange={(e) =>
                        setEditForm({
                          ...editForm,
                          critical_min: e.target.value === '' ? null : Number(e.target.value),
                        })
                      }
                      className="w-1/2 rounded border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white"
                    />
                    <input
                      type="number"
                      placeholder="Max"
                      value={editForm.critical_max ?? ''}
                      onChange={(e) =>
                        setEditForm({
                          ...editForm,
                          critical_max: e.target.value === '' ? null : Number(e.target.value),
                        })
                      }
                      className="w-1/2 rounded border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-2 border-t border-slate-750 pt-4">
              <button
                onClick={() => setEditingCandidate(null)}
                className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-700"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={savingEdit}
                className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-4 py-1.5 text-xs font-semibold text-white shadow hover:bg-sky-400"
              >
                {savingEdit && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Save & Re-validate
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 2: Human Review Decision */}
      {reviewModalCandidate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-850 p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white">
              {reviewDecision === 'APPROVED' ? 'Approve Signal Mapping' : 'Reject Signal Mapping'}
            </h3>
            <p className="mt-1 text-xs text-slate-400">
              Target node: <span className="font-mono text-sky-400">{reviewModalCandidate.display_name}</span>
            </p>

            <div className="mt-4">
              <label className="block text-xs font-semibold text-slate-300">
                Decision Rationale / Review Notes (Optional)
              </label>
              <textarea
                value={reviewReason}
                onChange={(e) => setReviewReason(e.target.value)}
                placeholder="Enter justification or engineering notes for this decision..."
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 p-2.5 text-xs text-white focus:border-sky-500 focus:outline-none"
                rows={3}
              />
            </div>

            <div className="mt-5 flex justify-end gap-2 border-t border-slate-750 pt-4">
              <button
                onClick={() => setReviewModalCandidate(null)}
                className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-700"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitReview}
                disabled={submittingReview}
                className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-xs font-semibold text-white shadow ${
                  reviewDecision === 'APPROVED'
                    ? 'bg-emerald-600 hover:bg-emerald-500'
                    : 'bg-rose-600 hover:bg-rose-500'
                }`}
              >
                {submittingReview && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Confirm {reviewDecision}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 3: Audit Trail for Candidate */}
      {auditCandidate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-850 p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-750 pb-3">
              <h3 className="text-base font-bold text-white">Immutable Review & Audit History</h3>
              <button onClick={() => setAuditCandidate(null)} className="text-slate-400 hover:text-white">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 max-h-[350px] overflow-y-auto space-y-3 pr-2 text-xs">
              {auditCandidate.review_history && auditCandidate.review_history.length > 0 ? (
                auditCandidate.review_history.map((h, idx) => (
                  <div key={idx} className="rounded-lg border border-slate-750 bg-slate-900/60 p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-sky-400 uppercase text-[11px]">
                        {h.action || h.decision}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">
                        {new Date(h.timestamp).toLocaleString()}
                      </span>
                    </div>
                    <p className="mt-1 text-slate-300 text-xs">{h.reason || 'No description provided.'}</p>
                    <div className="mt-2 text-[10px] text-slate-400">
                      User: <span className="text-slate-200">{h.user_email || h.user_id || 'System'}</span>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-center text-slate-500">No review history recorded yet.</p>
              )}
            </div>

            <div className="mt-4 flex justify-end border-t border-slate-750 pt-3">
              <button
                onClick={() => setAuditCandidate(null)}
                className="rounded-lg bg-slate-800 px-4 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-700"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 4: Import Discovery JSON */}
      {showImportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-xl rounded-xl border border-slate-700 bg-slate-850 p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-750 pb-3">
              <h3 className="text-base font-bold text-white">Import Phase 8 Discovery Output</h3>
              <button onClick={() => setShowImportModal(false)} className="text-slate-400 hover:text-white">
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="mt-2 text-xs text-slate-400">
              Paste the JSON content of <code className="text-sky-400">signal_mapping_template.json</code> or{' '}
              <code className="text-sky-400">discovered_nodes.json</code> generated by the Phase 8 discovery utility.
            </p>

            <textarea
              value={importJsonText}
              onChange={(e) => setImportJsonText(e.target.value)}
              placeholder="Paste JSON here..."
              className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 font-mono text-xs text-white focus:border-sky-500 focus:outline-none"
              rows={10}
            />

            <div className="mt-4 flex justify-end gap-2 border-t border-slate-750 pt-3">
              <button
                onClick={() => setShowImportModal(false)}
                className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-700"
              >
                Cancel
              </button>
              <button
                onClick={handleImportJson}
                disabled={importing || !importJsonText.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-4 py-1.5 text-xs font-semibold text-white shadow hover:bg-sky-400 disabled:opacity-50"
              >
                {importing && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Import & Create Session
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


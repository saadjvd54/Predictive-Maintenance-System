'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { useRouter, useParams } from 'next/navigation'
import {
  Cpu,
  ArrowLeft,
  Building2,
  Calendar,
  Layers,
  Wrench,
  Radio,
  Lock,
  Plus,
  Edit2,
  Check,
  AlertTriangle,
  Activity,
  ShieldCheck,
  Loader2,
  GitBranch,
  X,
  ChevronRight,
  Info,
  Sliders,
  Brain,
  TrendingUp,
  Bot,
} from 'lucide-react'
import apiClient, {
  EquipmentItem,
  MachineComponentItem,
  EquipmentCategoryItem,
  SiteDetails,
  ProductionAreaItem,
  ProductionLineItem,
} from '@/lib/api-client'
import TagDiscoveryPanel from '@/components/equipment/tag-discovery-panel'
import SignalValidationPanel from '@/components/equipment/signal-validation-panel'
import SignalMappingWizard from '@/components/equipment/signal-mapping-wizard'
import MonitoringTab from '@/components/equipment/monitoring-tab'
import ConditionTab from '@/components/equipment/condition-tab'
import PredictiveTab from '@/components/equipment/predictive-tab'
import AiDiagnosticsTab from '@/components/equipment/ai-diagnostics-tab'
import CommissioningReviewPanel from '@/components/equipment/commissioning-review-panel'
import { DiscoveredTag } from '@/lib/api-client'

export default function EquipmentDetailClient({ initialId }: { initialId?: string }) {
  const router = useRouter()
  const routeParams = useParams()
  const [machineId, setMachineId] = useState<string>(() => {
    const fromParams = routeParams?.id as string
    if (fromParams && fromParams !== 'default') return fromParams
    if (typeof window !== 'undefined') {
      const parts = window.location.pathname.split('/').filter(Boolean)
      const last = parts[parts.length - 1]
      if (last && last !== 'default' && last !== 'equipment') return last
    }
    return initialId && initialId !== 'default' ? initialId : ''
  })

  useEffect(() => {
    const fromParams = routeParams?.id as string
    if (fromParams && fromParams !== 'default') {
      setMachineId(fromParams)
    } else if (typeof window !== 'undefined') {
      const parts = window.location.pathname.split('/').filter(Boolean)
      const last = parts[parts.length - 1]
      if (last && last !== 'default' && last !== 'equipment') {
        setMachineId(last)
      }
    }
  }, [routeParams, initialId])

  const [activeTab, setActiveTab] = useState<'components' | 'discovery' | 'commissioning' | 'signals' | 'monitoring' | 'condition' | 'predictive' | 'diagnostics'>('components')
  const [initialTagForWizard, setInitialTagForWizard] = useState<DiscoveredTag | null>(null)
  const [showDirectWizard, setShowDirectWizard] = useState(false)
  const [machine, setMachine] = useState<EquipmentItem | null>(null)
  const [components, setComponents] = useState<MachineComponentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Edit Machine Modal State
  const [showEditMachineModal, setShowEditMachineModal] = useState(false)
  const [categories, setCategories] = useState<EquipmentCategoryItem[]>([])
  const [editMachineData, setEditMachineData] = useState<{
    equipment_name: string
    category_id: string
    manufacturer: string
    model: string
    serial_number: string
    installation_date: string
    criticality: 'Low' | 'Medium' | 'High' | 'Critical'
    lifecycle_status: 'Active' | 'Inactive' | 'Under Maintenance' | 'Decommissioned'
    description: string
  }>({
    equipment_name: '',
    category_id: '',
    manufacturer: '',
    model: '',
    serial_number: '',
    installation_date: '',
    criticality: 'Medium',
    lifecycle_status: 'Active',
    description: '',
  })
  const [savingMachine, setSavingMachine] = useState(false)

  // Add Component Modal State
  const [showAddComponentModal, setShowAddComponentModal] = useState(false)
  const [parentForNewComponent, setParentForNewComponent] = useState<string | null>(null)
  const [newComponentData, setNewComponentData] = useState({
    component_name: '',
    component_code: '',
    component_type: 'Motor',
    manufacturer: '',
    model: '',
    serial_number: '',
    description: '',
    parent_component_id: '',
  })
  const [savingComponent, setSavingComponent] = useState(false)

  // Edit Component Modal State
  const [editingComponent, setEditingComponent] = useState<MachineComponentItem | null>(null)
  const [editComponentData, setEditComponentData] = useState({
    component_name: '',
    component_code: '',
    component_type: '',
    manufacturer: '',
    model: '',
    serial_number: '',
    description: '',
    parent_component_id: '',
  })
  const [updatingComponent, setUpdatingComponent] = useState(false)

  // Fetch machine and component data
  const fetchData = useCallback(
    async (isRefresh = false) => {
      if (!machineId || machineId === 'default') {
        setLoading(false)
        setRefreshing(false)
        return
      }

      if (isRefresh) setRefreshing(true)
      else setLoading(true)
      setError(null)

      try {
        const [machineRes, compRes, catRes] = await Promise.all([
          apiClient.getEquipmentDetail(machineId),
          apiClient.getComponents(machineId),
          apiClient.getCategories(),
        ])

        if (machineRes.data?.equipment) {
          const m = machineRes.data.equipment
          setMachine(m)
          setEditMachineData({
            equipment_name: m.equipment_name,
            category_id: m.category_id,
            manufacturer: m.manufacturer || '',
            model: m.model || '',
            serial_number: m.serial_number || '',
            installation_date: m.installation_date || '',
            criticality: m.criticality,
            lifecycle_status: m.lifecycle_status,
            description: m.description || '',
          })
        } else {
          setError(machineRes.error || 'Equipment not found')
        }

        if (compRes.data?.components) {
          setComponents(compRes.data.components)
        }

        if (catRes.data?.categories) {
          setCategories(catRes.data.categories)
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to fetch equipment details')
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    [machineId]
  )

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Handle Save Machine Edits
  const handleSaveMachine = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!machine) return
    setSavingMachine(true)
    try {
      const res = await apiClient.updateEquipment(machine.id, {
        equipment_name: editMachineData.equipment_name.trim(),
        category_id: editMachineData.category_id,
        manufacturer: editMachineData.manufacturer.trim() || undefined,
        model: editMachineData.model.trim() || undefined,
        serial_number: editMachineData.serial_number.trim() || undefined,
        installation_date: editMachineData.installation_date.trim() || undefined,
        criticality: editMachineData.criticality,
        lifecycle_status: editMachineData.lifecycle_status,
        description: editMachineData.description.trim() || undefined,
      })

      if (res.data?.equipment) {
        setMachine(res.data.equipment)
        setShowEditMachineModal(false)
      } else {
        alert(res.error || 'Failed to update equipment')
      }
    } finally {
      setSavingMachine(false)
    }
  }

  // Handle Add Component
  const handleAddComponent = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!machine || !newComponentData.component_name.trim()) return
    setSavingComponent(true)

    try {
      const res = await apiClient.addComponent(machine.id, {
        component_name: newComponentData.component_name.trim(),
        component_code: newComponentData.component_code.trim() || undefined,
        component_type: newComponentData.component_type || undefined,
        manufacturer: newComponentData.manufacturer.trim() || undefined,
        model: newComponentData.model.trim() || undefined,
        serial_number: newComponentData.serial_number.trim() || undefined,
        description: newComponentData.description.trim() || undefined,
        parent_component_id: newComponentData.parent_component_id || undefined,
      })

      if (res.data?.component) {
        setShowAddComponentModal(false)
        setNewComponentData({
          component_name: '',
          component_code: '',
          component_type: 'Motor',
          manufacturer: '',
          model: '',
          serial_number: '',
          description: '',
          parent_component_id: '',
        })
        fetchData(true)
      } else {
        alert(res.error || 'Failed to add component')
      }
    } finally {
      setSavingComponent(false)
    }
  }

  // Handle Update Component
  const handleUpdateComponent = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingComponent) return
    setUpdatingComponent(true)

    try {
      const res = await apiClient.updateComponent(editingComponent.id, {
        component_name: editComponentData.component_name.trim(),
        component_code: editComponentData.component_code.trim() || undefined,
        component_type: editComponentData.component_type || undefined,
        manufacturer: editComponentData.manufacturer.trim() || undefined,
        model: editComponentData.model.trim() || undefined,
        serial_number: editComponentData.serial_number.trim() || undefined,
        description: editComponentData.description.trim() || undefined,
        parent_component_id: editComponentData.parent_component_id || null,
      })

      if (res.data?.component) {
        setEditingComponent(null)
        fetchData(true)
      } else {
        alert(res.error || 'Failed to update component')
      }
    } finally {
      setUpdatingComponent(false)
    }
  }

  const openAddComponent = (parentId?: string) => {
    setNewComponentData((prev) => ({
      ...prev,
      parent_component_id: parentId || '',
    }))
    setShowAddComponentModal(true)
  }

  const openEditComponent = (comp: MachineComponentItem) => {
    setEditingComponent(comp)
    setEditComponentData({
      component_name: comp.component_name,
      component_code: comp.component_code || '',
      component_type: comp.component_type || 'Motor',
      manufacturer: comp.manufacturer || '',
      model: comp.model || '',
      serial_number: comp.serial_number || '',
      description: comp.description || '',
      parent_component_id: comp.parent_component_id || '',
    })
  }

  // Flatten component list for select options (excluding self when editing)
  const getAllFlattenedComponents = (list: MachineComponentItem[]): MachineComponentItem[] => {
    const flat: MachineComponentItem[] = []
    const traverse = (items: MachineComponentItem[]) => {
      items.forEach((item) => {
        flat.push(item)
        if (item.subcomponents && item.subcomponents.length > 0) {
          traverse(item.subcomponents)
        }
      })
    }
    traverse(list)
    return flat
  }

  const flattenedComponents = getAllFlattenedComponents(components)

  const getCriticalityBadge = (crit: string) => {
    switch (crit) {
      case 'Critical':
        return 'bg-rose-50 text-rose-700 border-rose-200'
      case 'High':
        return 'bg-amber-50 text-amber-700 border-amber-200'
      case 'Medium':
        return 'bg-blue-50 text-blue-700 border-blue-200'
      default:
        return 'bg-slate-50 text-slate-700 border-slate-200'
    }
  }

  const getLifecycleBadge = (status: string) => {
    switch (status) {
      case 'Active':
        return 'bg-emerald-50 text-emerald-700 border-emerald-200'
      case 'Under Maintenance':
        return 'bg-amber-50 text-amber-700 border-amber-200'
      case 'Decommissioned':
        return 'bg-rose-50 text-rose-700 border-rose-200'
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200'
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center text-slate-400">
        <Loader2 className="size-8 animate-spin text-[#1685ff]" />
        <p className="mt-3 text-xs font-semibold">Loading equipment asset...</p>
      </div>
    )
  }

  if (error || !machine) {
    return (
      <div className="space-y-4">
        <Link
          href="/dashboard/equipment"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-[#1685ff]"
        >
          <ArrowLeft className="size-3.5" />
          <span>Back to Equipment Registry</span>
        </Link>
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-xs text-rose-700">
          <p className="text-base font-bold">Unable to load equipment asset</p>
          <p className="mt-1">{error || 'Equipment not found.'}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Top Breadcrumb & Controls */}
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div className="space-y-1">
          <Link
            href="/dashboard/equipment"
            className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 transition hover:text-[#1685ff]"
          >
            <ArrowLeft className="size-3.5" />
            <span>Back to Equipment Registry</span>
          </Link>
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <span className="font-mono text-sm font-bold text-[#1685ff]">
              {machine.asset_code}
            </span>
            <span className="text-slate-300">/</span>
            <h1 className="text-2xl font-bold tracking-tight text-[#102c50]">
              {machine.equipment_name}
            </h1>
          </div>
          <p className="text-xs text-slate-500">
            {machine.category_name} · Plant: {machine.site_name}
            {machine.production_area_name ? ` · Area: ${machine.production_area_name}` : ''}
            {machine.production_line_name ? ` · Line: ${machine.production_line_name}` : ''}
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowEditMachineModal(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            <Edit2 className="size-3.5 text-slate-400" />
            <span>Edit Specifications</span>
          </button>
          <button
            onClick={() => openAddComponent()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#1685ff] px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-[#126bd0]"
          >
            <Plus className="size-4" />
            <span>Add Component</span>
          </button>
        </div>
      </div>

      {/* Status & Criticality Badges Bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold text-slate-400">Criticality:</span>
          <span
            className={`rounded-full border px-2.5 py-0.5 text-xs font-bold ${getCriticalityBadge(
              machine.criticality
            )}`}
          >
            {machine.criticality} Tier
          </span>
        </div>

        <div className="h-4 w-px bg-slate-200" />

        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold text-slate-400">Lifecycle:</span>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${getLifecycleBadge(
              machine.lifecycle_status
            )}`}
          >
            <span
              className={`size-1.5 rounded-full ${
                machine.lifecycle_status === 'Active'
                  ? 'bg-emerald-500 animate-pulse'
                  : 'bg-slate-400'
              }`}
            />
            {machine.lifecycle_status}
          </span>
        </div>

        <div className="h-4 w-px bg-slate-200" />

        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold text-slate-400">Industrial Gateway:</span>
          <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
            <Lock className="size-3 text-slate-400" />
            <span>{machine.connection_status}</span>
          </span>
        </div>

        <div className="h-4 w-px bg-slate-200" />

        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold text-slate-400">Monitoring Engine:</span>
          <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
            <Activity className="size-3 text-slate-400" />
            <span>{machine.monitoring_status}</span>
          </span>
        </div>
      </div>

      {/* Grid: Specifications & Connectivity Placeholder */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left 2 Cols: Machine Technical Specifications & Location */}
        <div className="space-y-6 lg:col-span-2">
          {/* Card: Technical Specs */}
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-sm font-bold text-[#102c50]">Technical Specifications</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div>
                <span className="text-[11px] font-semibold text-slate-400">Manufacturer</span>
                <p className="text-xs font-medium text-slate-800">
                  {machine.manufacturer || 'Unspecified'}
                </p>
              </div>

              <div>
                <span className="text-[11px] font-semibold text-slate-400">Model / Type</span>
                <p className="text-xs font-medium text-slate-800">{machine.model || 'Unspecified'}</p>
              </div>

              <div>
                <span className="text-[11px] font-semibold text-slate-400">Serial Number</span>
                <p className="font-mono text-xs font-medium text-slate-800">
                  {machine.serial_number || 'None'}
                </p>
              </div>

              <div>
                <span className="text-[11px] font-semibold text-slate-400">Commissioning Date</span>
                <p className="text-xs font-medium text-slate-800">
                  {machine.installation_date || 'Not specified'}
                </p>
              </div>

              <div>
                <span className="text-[11px] font-semibold text-slate-400">Registered On</span>
                <p className="text-xs font-medium text-slate-800">
                  {machine.created_at ? new Date(machine.created_at).toLocaleDateString() : 'N/A'}
                </p>
              </div>

              <div>
                <span className="text-[11px] font-semibold text-slate-400">Commissioned By</span>
                <p className="text-xs font-medium text-slate-800">
                  {machine.creator_name || 'System Administrator'}
                </p>
              </div>

              {machine.description && (
                <div className="sm:col-span-2 border-t border-slate-100 pt-3">
                  <span className="text-[11px] font-semibold text-slate-400">Operational Notes</span>
                  <p className="mt-1 text-xs leading-relaxed text-slate-600">
                    {machine.description}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Card: Plant Hierarchy & Location */}
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-sm font-bold text-[#102c50]">Plant Hierarchy & Physical Assignment</h2>
            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="flex-1 rounded-xl border border-slate-100 bg-slate-50/50 p-3.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                  Site / Facility
                </span>
                <p className="mt-1 text-xs font-bold text-[#102c50]">{machine.site_name}</p>
              </div>

              <ChevronRight className="hidden size-4 text-slate-300 sm:block" />

              <div className="flex-1 rounded-xl border border-slate-100 bg-slate-50/50 p-3.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                  Production Area
                </span>
                <p className="mt-1 text-xs font-bold text-[#102c50]">
                  {machine.production_area_name || 'Standalone in Factory'}
                </p>
              </div>

              <ChevronRight className="hidden size-4 text-slate-300 sm:block" />

              <div className="flex-1 rounded-xl border border-slate-100 bg-slate-50/50 p-3.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                  Manufacturing Line
                </span>
                <p className="mt-1 text-xs font-bold text-[#102c50]">
                  {machine.production_line_name || 'Standalone Equipment'}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Right 1 Col: Industrial Connectivity & Monitoring Placeholder (Protected) */}
        <div className="space-y-6 lg:col-span-1">
          <div className="rounded-2xl border border-blue-200 bg-gradient-to-br from-blue-50/60 to-slate-50/80 p-6 shadow-sm">
            <div className="flex items-center justify-between text-xs font-bold text-[#1685ff]">
              <div className="flex items-center gap-1.5">
                <Radio className="size-4" />
                <span>Industrial Telemetry</span>
              </div>
              <span className="flex items-center gap-1 rounded bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-[#1685ff]">
                <Lock className="size-3" /> Protected
              </span>
            </div>

            <h3 className="mt-3 text-sm font-bold text-[#102c50]">OPC UA & Sensor Ingestion</h3>
            <p className="mt-2 text-xs leading-relaxed text-slate-600">
              Live industrial connectivity protocols (OPC UA DA/HA, MQTT Sparkplug B) will be integrated in{' '}
              <strong>Phase 4</strong>.
            </p>

            <div className="mt-4 space-y-2 border-t border-blue-200/60 pt-3 text-xs text-slate-600">
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Connection State:</span>
                <span className="font-semibold text-slate-700">{machine.connection_status}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Monitoring Engine:</span>
                <span className="font-semibold text-slate-700">{machine.monitoring_status}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Telemetry Stream:</span>
                <span className="font-semibold text-slate-400">Offline (Awaiting Phase 4)</span>
              </div>
            </div>

            <div className="mt-5 rounded-xl border border-blue-100 bg-white/70 p-3 text-[11px] leading-relaxed text-blue-900">
              <Info className="mb-1 size-3.5 text-[#1685ff]" />
              Client-side spoofing of connectivity is disallowed by server-side security decorators.
            </div>

            <button
              onClick={() => setActiveTab('discovery')}
              className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#1685ff] px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-[#126bd0]"
            >
              <Radio className="size-3.5" />
              <span>Discover OPC UA Tags</span>
            </button>
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-200">
        <button
          onClick={() => setActiveTab('components')}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition ${
            activeTab === 'components'
              ? 'border-[#1685ff] text-[#1685ff]'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Layers className="size-4" />
          <span>Machine Components ({flattenedComponents.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('discovery')}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition ${
            activeTab === 'discovery'
              ? 'border-[#1685ff] text-[#1685ff]'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Radio className="size-4" />
          <span>OPC UA Tag Discovery</span>
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-bold text-[#1685ff]">
            Step 5
          </span>
        </button>

        <button
          onClick={() => setActiveTab('commissioning')}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition ${
            activeTab === 'commissioning'
              ? 'border-[#1685ff] text-[#1685ff]'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <ShieldCheck className="size-4" />
          <span>Commissioning Review</span>
          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-800">
            Phase 9
          </span>
        </button>

        <button
          onClick={() => setActiveTab('signals')}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition ${
            activeTab === 'signals'
              ? 'border-[#1685ff] text-[#1685ff]'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Sliders className="size-4" />
          <span>Signals & Mapping</span>
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-800">
            Step 6
          </span>
        </button>

        <button
          onClick={() => setActiveTab('monitoring')}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition ${
            activeTab === 'monitoring'
              ? 'border-[#1685ff] text-[#1685ff]'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Activity className="size-4" />
          <span>Live Monitoring</span>
          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-800">
            Step 7
          </span>
        </button>

        <button
          onClick={() => setActiveTab('condition')}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition ${
            activeTab === 'condition'
              ? 'border-[#1685ff] text-[#1685ff]'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Brain className="size-4" />
          <span>Condition & AI Anomalies</span>
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-bold text-[#1685ff]">
            Phase 5
          </span>
        </button>

        <button
          onClick={() => setActiveTab('predictive')}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition ${
            activeTab === 'predictive'
              ? 'border-[#1685ff] text-[#1685ff]'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <TrendingUp className="size-4" />
          <span>Predictive Intelligence & RUL</span>
          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-800">
            Phase 6
          </span>
        </button>

        <button
          onClick={() => setActiveTab('diagnostics')}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition ${
            activeTab === 'diagnostics'
              ? 'border-[#1685ff] text-[#1685ff]'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Bot className="size-4" />
          <span>Multi-Agent Diagnostics & RAG</span>
          <span className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-bold text-purple-800">
            Phase 7
          </span>
        </button>
      </div>

      {activeTab === 'diagnostics' ? (
        <AiDiagnosticsTab
          machineId={machine.id}
          machineName={machine.equipment_name}
        />
      ) : activeTab === 'predictive' ? (
        <PredictiveTab
          machineId={machine.id}
          machineName={machine.equipment_name}
        />
      ) : activeTab === 'condition' ? (
        <ConditionTab
          machineId={machine.id}
          machineName={machine.equipment_name}
        />
      ) : activeTab === 'monitoring' ? (
        <MonitoringTab
          machineId={machine.id}
          machineName={machine.equipment_name}
          onSwitchToMapping={() => setActiveTab('signals')}
        />
      ) : activeTab === 'discovery' ? (
        <TagDiscoveryPanel
          machineId={machine.id}
          machineName={machine.equipment_name}
          onProceedToMapping={(selectedTags) => {
            if (selectedTags.length > 0) {
              setInitialTagForWizard(selectedTags[0])
              setShowDirectWizard(true)
            }
            setActiveTab('commissioning')
          }}
        />
      ) : activeTab === 'commissioning' ? (
        <CommissioningReviewPanel
          machineId={machine.id}
          machineName={machine.equipment_name}
          assetCode={machine.asset_code}
          onActivationSuccess={() => {
            fetchData(true)
            setActiveTab('signals')
          }}
        />
      ) : activeTab === 'signals' ? (
        <>
          <SignalValidationPanel
            machineId={machine.id}
            machineName={machine.equipment_name}
            components={flattenedComponents}
          />
          <SignalMappingWizard
            machineId={machine.id}
            machineName={machine.equipment_name}
            isOpen={showDirectWizard}
            onClose={() => {
              setShowDirectWizard(false)
              setInitialTagForWizard(null)
            }}
            onSuccess={() => {
              setShowDirectWizard(false)
              setInitialTagForWizard(null)
            }}
            initialTag={initialTagForWizard}
            components={flattenedComponents}
          />
        </>
      ) : (
        /* Main Bottom Section: Hierarchical Machine Components */
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col justify-between gap-4 border-b border-slate-100 pb-4 sm:flex-row sm:items-center">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-[#102c50]">Equipment Component Hierarchy</h2>
                <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
                  {flattenedComponents.length} {flattenedComponents.length === 1 ? 'part' : 'parts'}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-slate-500">
                Drive motors, bearings, gearboxes, pumps, and subcomponents tracked for vibration, temperature, and wear.
              </p>
            </div>

            <button
              onClick={() => openAddComponent()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#1685ff] px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-[#126bd0]"
            >
              <Plus className="size-4" />
              <span>Add Component</span>
            </button>
          </div>

          {/* Component Tree Display */}
          {components.length === 0 ? (
            <div className="flex min-h-[220px] flex-col items-center justify-center p-8 text-center">
              <div className="grid size-12 place-items-center rounded-xl bg-blue-50 text-[#1685ff]">
                <Layers className="size-6" />
              </div>
              <h3 className="mt-3 text-sm font-bold text-[#102c50]">No components recorded yet</h3>
              <p className="mt-1 max-w-sm text-xs leading-relaxed text-slate-500">
                Break down this machine into subcomponents (e.g. Main Drive Motor, Vacuum Pump, Sealing Rollers, Bearings)
                for granular diagnostic analysis.
              </p>
              <button
                onClick={() => openAddComponent()}
                className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
              >
                <Plus className="size-3.5 text-[#1685ff]" />
                <span>Add Primary Component</span>
              </button>
            </div>
          ) : (
            <div className="mt-4 divide-y divide-slate-100">
              {components.map((comp) => (
                <ComponentNode
                  key={comp.id}
                  component={comp}
                  level={0}
                  onAddSubcomponent={(parentId) => openAddComponent(parentId)}
                  onEdit={(c) => openEditComponent(c)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* MODAL: Edit Machine Specifications */}
      {showEditMachineModal && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4 backdrop-blur-sm">
          <div className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-bold text-[#102c50]">Edit Equipment Specifications</h3>
                <p className="text-xs text-slate-500">Asset Code: {machine.asset_code}</p>
              </div>
              <button
                onClick={() => setShowEditMachineModal(false)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <X className="size-4" />
              </button>
            </div>

            <form onSubmit={handleSaveMachine} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700">Equipment Name</label>
                <input
                  type="text"
                  value={editMachineData.equipment_name}
                  onChange={(e) =>
                    setEditMachineData({ ...editMachineData, equipment_name: e.target.value })
                  }
                  required
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-semibold text-slate-700">Category</label>
                  <select
                    value={editMachineData.category_id}
                    onChange={(e) =>
                      setEditMachineData({ ...editMachineData, category_id: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  >
                    {categories.map((cat) => (
                      <option key={cat.id} value={cat.id}>
                        {cat.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">Criticality</label>
                  <select
                    value={editMachineData.criticality}
                    onChange={(e) =>
                      setEditMachineData({
                        ...editMachineData,
                        criticality: e.target.value as 'Low' | 'Medium' | 'High' | 'Critical',
                      })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  >
                    <option value="Critical">Critical</option>
                    <option value="High">High</option>
                    <option value="Medium">Medium</option>
                    <option value="Low">Low</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">Manufacturer</label>
                  <input
                    type="text"
                    value={editMachineData.manufacturer}
                    onChange={(e) =>
                      setEditMachineData({ ...editMachineData, manufacturer: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">Model / Type</label>
                  <input
                    type="text"
                    value={editMachineData.model}
                    onChange={(e) =>
                      setEditMachineData({ ...editMachineData, model: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">Serial Number</label>
                  <input
                    type="text"
                    value={editMachineData.serial_number}
                    onChange={(e) =>
                      setEditMachineData({ ...editMachineData, serial_number: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">
                    Lifecycle Status
                  </label>
                  <select
                    value={editMachineData.lifecycle_status}
                    onChange={(e) =>
                      setEditMachineData({
                        ...editMachineData,
                        lifecycle_status: e.target.value as
                          | 'Active'
                          | 'Inactive'
                          | 'Under Maintenance'
                          | 'Decommissioned',
                      })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  >
                    <option value="Active">Active</option>
                    <option value="Under Maintenance">Under Maintenance</option>
                    <option value="Inactive">Inactive</option>
                    <option value="Decommissioned">Decommissioned</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700">Operational Notes</label>
                <textarea
                  rows={3}
                  value={editMachineData.description}
                  onChange={(e) =>
                    setEditMachineData({ ...editMachineData, description: e.target.value })
                  }
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setShowEditMachineModal(false)}
                  className="rounded-lg border border-slate-200 px-3.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingMachine}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#1685ff] px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#126bd0] disabled:opacity-50"
                >
                  {savingMachine && <Loader2 className="size-3.5 animate-spin" />}
                  <span>Save Changes</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Add Component */}
      {showAddComponentModal && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-bold text-[#102c50]">Add Machine Component</h3>
                <p className="text-xs text-slate-500">Asset: {machine.equipment_name}</p>
              </div>
              <button
                onClick={() => setShowAddComponentModal(false)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <X className="size-4" />
              </button>
            </div>

            <form onSubmit={handleAddComponent} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700">
                  Component Name <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. Main Drive Motor, Spindle Bearings, Heating Element"
                  value={newComponentData.component_name}
                  onChange={(e) =>
                    setNewComponentData({ ...newComponentData, component_name: e.target.value })
                  }
                  required
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-semibold text-slate-700">
                    Component Code (Optional)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. MTR-01, BRG-DE-02"
                    value={newComponentData.component_code}
                    onChange={(e) =>
                      setNewComponentData({
                        ...newComponentData,
                        component_code: e.target.value.toUpperCase(),
                      })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">
                    Component Type
                  </label>
                  <select
                    value={newComponentData.component_type}
                    onChange={(e) =>
                      setNewComponentData({ ...newComponentData, component_type: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  >
                    <option value="Motor">Motor / Drive</option>
                    <option value="Bearing">Bearing (Drive / Non-Drive End)</option>
                    <option value="Gearbox">Gearbox / Transmission</option>
                    <option value="Heating Element">Heating Element / Sealer</option>
                    <option value="Pump">Pump / Impeller</option>
                    <option value="Compressor">Compressor Stage</option>
                    <option value="Sensor">Vibration / Temp Sensor</option>
                    <option value="Valve">Valve / Actuator</option>
                    <option value="Seal">Mechanical Seal / Gasket</option>
                    <option value="Other">Other Subassembly</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">Manufacturer</label>
                  <input
                    type="text"
                    placeholder="e.g. Siemens, SKF, SEW-Eurodrive"
                    value={newComponentData.manufacturer}
                    onChange={(e) =>
                      setNewComponentData({ ...newComponentData, manufacturer: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">Model</label>
                  <input
                    type="text"
                    placeholder="e.g. 1LA7 083-4AA10, 6205-2RSH"
                    value={newComponentData.model}
                    onChange={(e) =>
                      setNewComponentData({ ...newComponentData, model: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>
              </div>

              {/* Parent Component Selection */}
              <div>
                <label className="block text-xs font-semibold text-slate-700">
                  Parent Component (For Hierarchical Subassembly)
                </label>
                <select
                  value={newComponentData.parent_component_id}
                  onChange={(e) =>
                    setNewComponentData({
                      ...newComponentData,
                      parent_component_id: e.target.value,
                    })
                  }
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                >
                  <option value="">None (Top-Level Machine Component)</option>
                  {flattenedComponents.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.component_name} {c.component_code ? `[${c.component_code}]` : ''}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-[11px] text-slate-400">
                  Select a parent to nest this part (e.g., Bearings nested under Main Drive Motor).
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700">Description</label>
                <textarea
                  rows={2}
                  placeholder="Installation notes, operating rpm, or temperature rating..."
                  value={newComponentData.description}
                  onChange={(e) =>
                    setNewComponentData({ ...newComponentData, description: e.target.value })
                  }
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setShowAddComponentModal(false)}
                  className="rounded-lg border border-slate-200 px-3.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingComponent}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#1685ff] px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#126bd0] disabled:opacity-50"
                >
                  {savingComponent && <Loader2 className="size-3.5 animate-spin" />}
                  <span>Save Component</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Edit Component */}
      {editingComponent && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-bold text-[#102c50]">Edit Component</h3>
                <p className="text-xs text-slate-500">{editingComponent.component_name}</p>
              </div>
              <button
                onClick={() => setEditingComponent(null)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <X className="size-4" />
              </button>
            </div>

            <form onSubmit={handleUpdateComponent} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700">Component Name</label>
                <input
                  type="text"
                  value={editComponentData.component_name}
                  onChange={(e) =>
                    setEditComponentData({ ...editComponentData, component_name: e.target.value })
                  }
                  required
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-semibold text-slate-700">
                    Component Code
                  </label>
                  <input
                    type="text"
                    value={editComponentData.component_code}
                    onChange={(e) =>
                      setEditComponentData({
                        ...editComponentData,
                        component_code: e.target.value.toUpperCase(),
                      })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">Type</label>
                  <input
                    type="text"
                    value={editComponentData.component_type}
                    onChange={(e) =>
                      setEditComponentData({ ...editComponentData, component_type: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">Manufacturer</label>
                  <input
                    type="text"
                    value={editComponentData.manufacturer}
                    onChange={(e) =>
                      setEditComponentData({ ...editComponentData, manufacturer: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700">Model</label>
                  <input
                    type="text"
                    value={editComponentData.model}
                    onChange={(e) =>
                      setEditComponentData({ ...editComponentData, model: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                  />
                </div>
              </div>

              {/* Reparenting */}
              <div>
                <label className="block text-xs font-semibold text-slate-700">
                  Parent Component
                </label>
                <select
                  value={editComponentData.parent_component_id}
                  onChange={(e) =>
                    setEditComponentData({
                      ...editComponentData,
                      parent_component_id: e.target.value,
                    })
                  }
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                >
                  <option value="">None (Top-Level Machine Component)</option>
                  {flattenedComponents
                    .filter((c) => c.id !== editingComponent.id)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.component_name} {c.component_code ? `[${c.component_code}]` : ''}
                      </option>
                    ))}
                </select>
                <p className="mt-1 text-[11px] text-slate-400">
                  Backend automatically verifies cycle prevention against ancestor loops.
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700">Description</label>
                <textarea
                  rows={2}
                  value={editComponentData.description}
                  onChange={(e) =>
                    setEditComponentData({ ...editComponentData, description: e.target.value })
                  }
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 outline-none focus:border-[#1685ff] focus:ring-2 focus:ring-[#1685ff]/20"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setEditingComponent(null)}
                  className="rounded-lg border border-slate-200 px-3.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={updatingComponent}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#1685ff] px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#126bd0] disabled:opacity-50"
                >
                  {updatingComponent && <Loader2 className="size-3.5 animate-spin" />}
                  <span>Update Component</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

// ==============================================================================
// RECURSIVE COMPONENT NODE VIEW
// ==============================================================================

function ComponentNode({
  component,
  level,
  onAddSubcomponent,
  onEdit,
}: {
  component: MachineComponentItem
  level: number
  onAddSubcomponent: (parentId: string) => void
  onEdit: (comp: MachineComponentItem) => void
}) {
  const hasSub = component.subcomponents && component.subcomponents.length > 0

  return (
    <div className={`py-3.5 ${level > 0 ? 'ml-6 border-l-2 border-slate-200/80 pl-4' : ''}`}>
      <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2.5">
          <span
            className={`grid size-7 shrink-0 place-items-center rounded-lg text-xs font-bold ${
              level === 0 ? 'bg-blue-50 text-[#1685ff]' : 'bg-slate-100 text-slate-600'
            }`}
          >
            {level === 0 ? <Layers className="size-3.5" /> : <GitBranch className="size-3" />}
          </span>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-[#102c50]">
                {component.component_name}
              </span>
              {component.component_code && (
                <span className="font-mono text-[10px] font-semibold text-slate-500">
                  [{component.component_code}]
                </span>
              )}
              {component.component_type && (
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                  {component.component_type}
                </span>
              )}
            </div>
            <div className="mt-0.5 text-[11px] text-slate-500">
              {component.manufacturer ? `Mfr: ${component.manufacturer}` : ''}
              {component.model ? ` · Model: ${component.model}` : ''}
              {component.serial_number ? ` · S/N: ${component.serial_number}` : ''}
              {component.description ? ` — ${component.description}` : ''}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 pl-9 sm:pl-0">
          <button
            onClick={() => onAddSubcomponent(component.id)}
            className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-[#1685ff] shadow-sm hover:bg-blue-50/50"
            title="Add Subcomponent"
          >
            <Plus className="size-3" />
            <span>Add Subpart</span>
          </button>
          <button
            onClick={() => onEdit(component)}
            className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 shadow-sm hover:bg-slate-50"
            title="Edit Component"
          >
            <Edit2 className="size-3 text-slate-400" />
            <span>Edit</span>
          </button>
        </div>
      </div>

      {/* Render Nested Subcomponents */}
      {hasSub && (
        <div className="mt-2 space-y-1">
          {component.subcomponents!.map((sub) => (
            <ComponentNode
              key={sub.id}
              component={sub}
              level={level + 1}
              onAddSubcomponent={onAddSubcomponent}
              onEdit={onEdit}
            />
          ))}
        </div>
      )}
    </div>
  )
}


/**
 * PharmaPredict AI - Unified Frontend API Client
 * Connects frontend views to Flask backend REST API endpoints.
 */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== 'undefined'
    ? '/api/v1'
    : 'http://localhost:5000/api/v1');

export interface ApiResponse<T = unknown> {
  data?: T;
  error?: string;
  message?: string;
  status: number;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  database: string;
  capabilities: string[];
}

export interface UserProfile {
  id: string;
  organization_id: string;
  full_name: string;
  email: string;
  is_active: boolean;
  roles: string[];
  created_at: string;
}

export interface OrganizationDetails {
  id: string;
  name: string;
  slug: string;
  status: string;
  site_count: number;
  created_at: string;
}

export interface SiteDetails {
  id: string;
  organization_id: string;
  name: string;
  location?: string;
  code?: string;
  status: string;
}

export interface ProductionAreaItem {
  id: string;
  organization_id: string;
  site_id: string;
  site_name?: string;
  name: string;
  description?: string;
  lines_count?: number;
  machines_count?: number;
  created_at: string;
  updated_at?: string;
}

export interface ProductionLineItem {
  id: string;
  organization_id: string;
  site_id: string;
  site_name?: string;
  production_area_id?: string;
  production_area_name?: string;
  name: string;
  line_code?: string;
  description?: string;
  machines_count?: number;
  created_at: string;
  updated_at?: string;
}

export interface EquipmentCategoryItem {
  id: string;
  organization_id?: string;
  name: string;
  description?: string;
  is_default: boolean;
  created_at: string;
}

export interface MachineComponentItem {
  id: string;
  organization_id: string;
  machine_id: string;
  parent_component_id?: string;
  parent_component_name?: string;
  component_name: string;
  component_code?: string;
  component_type?: string;
  manufacturer?: string;
  model?: string;
  serial_number?: string;
  description?: string;
  subcomponents?: MachineComponentItem[];
  created_at: string;
  updated_at?: string;
}

export interface EquipmentItem {
  id: string;
  organization_id: string;
  site_id: string;
  site_name?: string;
  production_area_id?: string;
  production_area_name?: string;
  production_line_id?: string;
  production_line_name?: string;
  category_id: string;
  category_name?: string;
  asset_code: string;
  equipment_name: string;
  manufacturer?: string;
  model?: string;
  serial_number?: string;
  installation_date?: string;
  criticality: 'Low' | 'Medium' | 'High' | 'Critical';
  lifecycle_status: 'Active' | 'Inactive' | 'Under Maintenance' | 'Decommissioned';
  connection_status: 'Not Configured' | 'Configured' | 'Connected' | 'Disconnected' | 'Error';
  monitoring_status: 'Not Started' | 'Pending Validation' | 'Active' | 'Suspended';
  description?: string;
  created_by?: string;
  creator_name?: string;
  components_count: number;
  created_at: string;
  updated_at?: string;
}

export interface EquipmentSummary {
  total_machines: number;
  active_machines: number;
  high_criticality: number;
  connected_machines: number;
  by_criticality: {
    Low: number;
    Medium: number;
    High: number;
    Critical: number;
  };
  by_lifecycle: {
    Active: number;
    Inactive: number;
    'Under Maintenance': number;
    Decommissioned: number;
  };
  by_connection: {
    'Not Configured': number;
    Configured: number;
    Connected: number;
    Disconnected: number;
    Error: number;
  };
}

export interface DiscoveredTag {
  node_id: string;
  browse_name: string;
  display_name: string;
  node_class: string;
  data_type?: string;
  engineering_unit?: string;
  description?: string;
  access_level?: number;
  namespace: number;
  parent_node_id?: string;
  readable: boolean;
  writable: boolean;
  has_children: boolean;
  children?: DiscoveredTag[];
}

export interface SignalDefinitionItem {
  id: string;
  signal_code: string;
  name: string;
  signal_group: string;
  expected_data_type: string;
  standard_unit?: string;
  measurement_dimension?: string;
  description?: string;
  is_custom: boolean;
  organization_id?: string;
  created_at: string;
}

export interface MachineSignalItem {
  id: string;
  organization_id: string;
  machine_id: string;
  connector_id?: string;
  component_id?: string;
  component_name?: string;
  signal_definition_id: string;
  signal_code?: string;
  signal_name?: string;
  signal_group?: string;
  source_node_id: string;
  source_browse_name?: string;
  source_data_type?: string;
  source_unit?: string;
  normalized_unit?: string;
  scaling_factor: number;
  offset: number;
  sampling_interval_ms: number;
  mapping_version: number;
  validation_status: 'PENDING' | 'VALID' | 'WARNING' | 'INVALID';
  enabled: boolean;
  created_at: string;
  updated_at?: string;
  latest_validation?: SignalValidationResultItem;
}

export interface SignalValidationResultItem {
  id: string;
  organization_id: string;
  machine_signal_id: string;
  validation_status: 'VALID' | 'WARNING' | 'INVALID';
  validation_checks: Record<string, { passed: boolean; severity: string; message: string; details?: any }>;
  error_messages: string[];
  warning_messages: string[];
  sample_reading?: {
    raw_value: any;
    normalized_value: any;
    scaling_applied?: { factor: number; offset: number };
    source_unit?: string;
    normalized_unit?: string;
    quality?: string;
    timestamp?: string;
  };
  validated_at: string;
  mapping_version: number;
}

export interface MappingSummary {
  machine_id: string;
  total_signals: number;
  valid_count: number;
  warning_count: number;
  invalid_count: number;
  pending_count: number;
  group_breakdown: Record<string, number>;
  ready_for_monitoring: boolean;
}

export interface CreateSignalPayload {
  signal_definition_id: string;
  source_node_id: string;
  source_browse_name?: string;
  source_data_type?: string;
  source_unit?: string;
  normalized_unit?: string;
  custom_name?: string;
  component_id?: string;
  scaling_factor?: number;
  offset?: number;
  sampling_interval_ms?: number;
  enabled?: boolean;
}

export interface UpdateSignalPayload {
  custom_name?: string;
  component_id?: string;
  source_node_id?: string;
  source_browse_name?: string;
  source_data_type?: string;
  source_unit?: string;
  normalized_unit?: string;
  scaling_factor?: number;
  offset?: number;
  sampling_interval_ms?: number;
  enabled?: boolean;
}

export interface CreateEquipmentPayload {
  asset_code: string;
  equipment_name: string;
  site_id: string;
  category_id: string;
  production_area_id?: string;
  production_line_id?: string;
  manufacturer?: string;
  model?: string;
  serial_number?: string;
  installation_date?: string;
  criticality?: 'Low' | 'Medium' | 'High' | 'Critical';
  description?: string;
}

export interface UpdateEquipmentPayload {
  equipment_name?: string;
  site_id?: string;
  production_area_id?: string;
  production_line_id?: string;
  category_id?: string;
  manufacturer?: string;
  model?: string;
  serial_number?: string;
  installation_date?: string;
  criticality?: 'Low' | 'Medium' | 'High' | 'Critical';
  lifecycle_status?: 'Active' | 'Inactive' | 'Under Maintenance' | 'Decommissioned';
  description?: string;
}

export interface CreateComponentPayload {
  component_name: string;
  component_code?: string;
  component_type?: string;
  manufacturer?: string;
  model?: string;
  serial_number?: string;
  description?: string;
  parent_component_id?: string;
}

export interface UpdateComponentPayload {
  component_name?: string;
  component_code?: string;
  component_type?: string;
  manufacturer?: string;
  model?: string;
  serial_number?: string;
  description?: string;
  parent_component_id?: string | null;
}

export interface CreateProductionAreaPayload {
  site_id: string;
  name: string;
  description?: string;
}

export interface CreateProductionLinePayload {
  site_id: string;
  name: string;
  line_code?: string;
  production_area_id?: string;
  description?: string;
}

export interface AuthMeResponse {
  user: UserProfile;
  organization: OrganizationDetails;
  roles: string[];
  permissions: {
    is_platform_admin: boolean;
    is_org_admin: boolean;
    can_manage_maintenance: boolean;
    can_review_diagnostics: boolean;
    can_view: boolean;
  };
}

export interface LoginResponse {
  message: string;
  user: UserProfile;
  organization: OrganizationDetails;
  roles: string[];
  session_token: string;
  expires_at: string;
}

export interface DemoRequestPayload {
  fullName: string;
  companyName: string;
  workEmail: string;
  jobRole: string;
  message?: string;
}

export type MonitoringState =
  | 'STOPPED'
  | 'ACTIVATING'
  | 'ACTIVE'
  | 'DEGRADED'
  | 'STOPPING'
  | 'ERROR';

export type SignalFreshness =
  | 'FRESH'
  | 'DELAYED'
  | 'STALE'
  | 'UNAVAILABLE';

export interface MonitoringSessionItem {
  id: string;
  organization_id: string;
  machine_id: string;
  requested_by?: string | null;
  desired_state: MonitoringState;
  observed_state: MonitoringState;
  status_reason?: string | null;
  mapping_version: number;
  activated_at?: string | null;
  stopped_at?: string | null;
  created_at: string;
}

export interface SignalReadingItem {
  id: string;
  event_id: string;
  machine_id: string;
  organization_id: string;
  signal_id: string;
  signal_name?: string;
  signal_group?: string;
  source_node_id?: string;
  mapping_version?: number;
  source_timestamp?: string | null;
  server_timestamp?: string | null;
  gateway_received_at?: string | null;
  source_value?: string | number | boolean | null;
  normalized_value?: number | null;
  raw_value_numeric?: number | null;
  raw_value_boolean?: boolean | null;
  raw_value_string?: string | null;
  source_unit?: string | null;
  normalized_unit?: string | null;
  quality_code?: string;
  normalization_status?: string;
  freshness: SignalFreshness;
  age_seconds?: number;
  simulator_flag?: boolean;
  threshold_status?: 'NORMAL' | 'WARNING' | 'CRITICAL' | 'UNCONFIGURED';
  min_value?: number | null;
  max_value?: number | null;
  avg_value?: number | null;
  sample_count?: number;
  downsampled?: boolean;
}

export interface MonitoringStatusResponse {
  machine_id: string;
  machine_name: string;
  desired_state: MonitoringState;
  observed_state: MonitoringState;
  status_reason?: string | null;
  activated_at?: string | null;
  active_subscriptions: number;
  total_mapped_signals: number;
  can_activate: boolean;
  activation_precondition_reason?: string;
  buffer_metrics?: {
    queue_depth: number;
    buffered_readings: number;
    dropped_readings: number;
  };
  simulator_flag: boolean;
}

export interface SignalThresholdItem {
  id?: string;
  signal_id: string;
  signal_name?: string;
  machine_id?: string;
  warning_min?: number | null;
  warning_max?: number | null;
  critical_min?: number | null;
  critical_max?: number | null;
  unit?: string | null;
  notes?: string | null;
  is_active?: boolean;
  configured: boolean;
  source?: 'signal_thresholds' | 'baseline_expected' | 'unconfigured';
}

export interface EquipmentThresholdsResponse {
  machine_id: string;
  organization_id?: string;
  thresholds: Record<string, SignalThresholdItem>;
}

export interface HistoricalReadingsResponse {
  machine_id: string;
  count: number;
  readings: SignalReadingItem[];
  thresholds?: Record<string, SignalThresholdItem>;
  downsampled?: boolean;
  simulator_flag: boolean;
}

export interface GatewayHealthResponse {
  gateway_id: string;
  machine_id?: string | null;
  connection_status: string;
  last_heartbeat?: string | null;
  latency_ms?: number | null;
  queue_depth: number;
  buffered_readings: number;
  dropped_readings: number;
  reconnect_attempts: number;
  cpu_usage_pct?: number | null;
  memory_usage_mb?: number | null;
  status_details?: string | null;
  reported_at?: string | null;
}

// =============================================================================
// PHASE 3 STEP 3.3: PLANT-WIDE OBSERVABILITY & FLEET MONITORING TYPES
// =============================================================================

export type FleetEquipmentStatus =
  | 'HEALTHY'
  | 'WARNING'
  | 'CRITICAL'
  | 'OFFLINE'
  | 'STALE'
  | 'NOT CONFIGURED';

export interface FleetOverviewResponse {
  organization_id: string;
  generated_at: string;
  total_equipment: number;
  monitoring_equipment: number;
  healthy_equipment: number;
  warning_equipment: number;
  critical_equipment: number;
  offline_equipment: number;
  stale_equipment: number;
  not_configured_equipment: number;
  active_alerts_count: number;
  critical_alerts_count: number;
  warning_alerts_count: number;
  simulator_flag: boolean;
}

export interface FleetThresholdBreach {
  signal_id: string;
  value: number;
  unit?: string | null;
  status: 'WARNING' | 'CRITICAL';
}

export interface FleetMachineItem {
  id: string;
  asset_code: string;
  equipment_name: string;
  category_id?: string | null;
  equipment_type: string;
  site_id?: string | null;
  site_name: string;
  location: string;
  status: FleetEquipmentStatus;
  monitoring_state: MonitoringState;
  desired_state: MonitoringState;
  is_actively_monitoring: boolean;
  signals_count: number;
  active_alerts_count: number;
  highest_alert_severity?: 'CRITICAL' | 'WARNING' | null;
  latest_telemetry_at?: string | null;
  data_freshness: SignalFreshness;
  telemetry_age_seconds?: number | null;
  threshold_breaches: FleetThresholdBreach[];
  created_at?: string | null;
}

export interface FleetMachinesResponse {
  items: FleetMachineItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
  status_counts: Record<FleetEquipmentStatus, number>;
  sites: Array<{ id: string; name: string; count: number }>;
  categories: Array<{ id: string; name: string; count: number }>;
}

export interface FleetAlertItem {
  id: string;
  machine_id: string;
  asset_code: string;
  equipment_name: string;
  site_name: string;
  severity: 'WARNING' | 'CRITICAL' | 'INFO';
  status: 'OPEN' | 'ACKNOWLEDGED' | 'UNDER_INVESTIGATION' | 'RESOLVED' | 'CLOSED';
  signal_name: string;
  observed_value?: number | null;
  first_detected_at?: string | null;
  last_detected_at?: string | null;
  acknowledged_by?: string | null;
  acknowledged_at?: string | null;
  resolution_notes?: string | null;
  anomaly_summary?: string | null;
}

export interface FleetAlertsResponse {
  organization_id: string;
  count: number;
  alerts: FleetAlertItem[];
}

// =============================================================================
// PHASE 5: CONDITION MONITORING, BASELINES & ANOMALY DETECTION TYPES
// =============================================================================

export type ConditionClassification =
  | 'NORMAL'
  | 'ATTENTION'
  | 'CRITICAL'
  | 'INSUFFICIENT_DATA'
  | 'MONITORING_UNAVAILABLE';

export type OperatingState =
  | 'IDLE'
  | 'STARTUP'
  | 'RUNNING'
  | 'HIGH_LOAD'
  | 'SHUTDOWN'
  | 'CLEANING'
  | 'UNKNOWN';

export type AnomalySeverity = 'INFO' | 'WARNING' | 'CRITICAL';
export type AlertStatus = 'OPEN' | 'ACKNOWLEDGED' | 'UNDER_INVESTIGATION' | 'RESOLVED' | 'CLOSED';

export interface DataQualityReport {
  machine_id: string;
  overall_state: string;
  evaluated_signals_count: number;
  issues_count: number;
  issues: Array<{
    signal_id?: string;
    signal_name?: string;
    issue_type: string;
    severity?: string;
    message: string;
  }>;
  evaluated_at: string;
}

export interface OperatingContextResponse {
  machine_id: string;
  current_state: OperatingState;
  confidence: number;
  method: string;
  supporting_signals: Record<string, number>;
  evaluated_at: string;
}

export interface BaselineStatistics {
  mean: number;
  median: number;
  std: number;
  min: number;
  max: number;
  p5: number;
  p25: number;
  p75: number;
  p95: number;
  iqr: number;
  mad: number;
  variability: number;
}

export interface BaselineProfileItem {
  id: string;
  name: string;
  machine_id: string;
  signal_id: string;
  signal_name?: string;
  operating_state: string;
  lifecycle_status: string;
  active_version_number?: number | null;
  active_version?: {
    id: string;
    version_number: number;
    sample_count: number;
    statistics: BaselineStatistics;
    validation_status: string;
    validation_notes?: string;
    approved_by?: string;
    approved_at?: string;
    created_at: string;
  } | null;
  versions?: Array<any>;
}

export interface AnomalyEvidenceItem {
  id: string;
  anomaly_id: string;
  signal_id: string;
  source_timestamp: string;
  observed_value: number;
  baseline_expected_value?: number | null;
  deviation_magnitude?: number | null;
  evidence_payload?: Record<string, any>;
}

export interface AnomalyEventItem {
  id: string;
  organization_id: string;
  machine_id: string;
  component_id?: string | null;
  detection_method: string;
  severity: AnomalySeverity;
  operating_state: OperatingState;
  status: string;
  first_detected_at: string;
  latest_detected_at: string;
  occurrence_count: number;
  anomaly_score: number;
  affected_signals: string[];
  summary: string;
  created_at: string;
  evidence?: AnomalyEvidenceItem[];
}

export interface ConditionSummaryResponse {
  machine_id: string;
  machine_name: string;
  condition_state: ConditionClassification;
  summary_reason: string;
  observed_at: string | null;
  operating_state: OperatingState;
  operating_confidence: number;
  data_quality_state: string;
  data_quality_issues: any[];
  open_alerts_count: number;
  active_anomaly_count: number;
  active_anomalies: AnomalyEventItem[];
  baseline_coverage: {
    total_signals: number;
    signals_with_active_baseline: number;
  };
}

export interface EquipmentAlertItem {
  id: string;
  organization_id: string;
  machine_id: string;
  machine_name?: string;
  anomaly_id: string;
  anomaly_summary?: string;
  severity: AnomalySeverity;
  status: AlertStatus;
  first_detected_at: string;
  last_detected_at: string;
  assigned_to?: string | null;
  acknowledged_by?: string | null;
  acknowledged_at?: string | null;
  resolution_notes?: string | null;
  created_at: string;
  updated_at: string;
  anomaly?: AnomalyEventItem;
  history?: Array<{
    id: string;
    old_status?: string | null;
    new_status: string;
    note?: string | null;
    created_at: string;
  }>;
}

export interface MLModelRegistryItem {
  registry: {
    id: string;
    machine_id: string;
    model_type: string;
    name: string;
    lifecycle_status: string;
    active_version_number: number;
  } | null;
  versions: Array<{
    id: string;
    version_number: number;
    feature_schema: any;
    hyperparameters: any;
    training_sample_count: number;
    training_dataset_ref: string;
    validation_metrics: any;
    status: string;
    created_at: string;
    approved_at?: string;
  }>;
}

// ============================================================================
// PHASE 6: FAILURE PREDICTION, RISK ESTIMATION & REMAINING USEFUL LIFE (RUL)
// ============================================================================

export type PredictionEligibilityState =
  | 'NOT_CONFIGURED'
  | 'INSUFFICIENT_DATA'
  | 'TRAINING_ELIGIBLE'
  | 'UNDER_VALIDATION'
  | 'PREDICTION_READY'
  | 'MODEL_UNAVAILABLE'
  | 'DATA_QUALITY_BLOCKED';

export type PredictiveRiskCategory = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type FailureVerificationStatus =
  | 'CONFIRMED'
  | 'SUSPECTED'
  | 'PREVENTIVE_MAINTENANCE'
  | 'INSPECTION'
  | 'PLANNED_SHUTDOWN'
  | 'UNVERIFIED';

export type PredictiveAlertStatus =
  | 'OPEN'
  | 'ACKNOWLEDGED'
  | 'UNDER_INVESTIGATION'
  | 'RESOLVED'
  | 'DISMISSED';

export interface FailureModeItem {
  id: string;
  organization_id?: string | null;
  category_id?: string | null;
  code: string;
  name: string;
  component_type?: string | null;
  description?: string | null;
  severity_impact: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  evidence_requirements?: Record<string, any>;
  relevant_signals?: string[];
  applicable_model_families?: string[];
  is_standard: boolean;
  created_at: string;
}

export interface FailureRecordItem {
  id: string;
  organization_id: string;
  machine_id: string;
  component_id?: string | null;
  failure_mode_id?: string | null;
  failure_mode_name?: string | null;
  failure_mode_code?: string | null;
  failure_started_at: string;
  failure_detected_at?: string | null;
  failure_confirmed_at?: string | null;
  restoration_completed_at?: string | null;
  failure_description: string;
  observed_symptoms?: string[];
  confirmed_root_cause?: string | null;
  maintenance_action?: string | null;
  downtime_minutes: number;
  record_source: string;
  verification_status: FailureVerificationStatus;
  verified_by?: string | null;
  created_at: string;
}

export interface PredictionEligibilityResponse {
  machine_id: string;
  eligibility_state: PredictionEligibilityState;
  can_train: boolean;
  can_predict: boolean;
  can_estimate_rul: boolean;
  reasons: string[];
  details: {
    signal_count: number;
    history_hours: number;
    verified_failure_count: number;
    unverified_maintenance_count: number;
    active_model_count: number;
    under_validation_model_count: number;
    data_quality_state?: string;
    issues?: any[];
  };
  evaluated_at: string;
}

export interface PredictionEvidenceItem {
  id: string;
  prediction_id: string;
  signal_id?: string | null;
  feature_name: string;
  feature_value: number;
  baseline_expected_value?: number | null;
  contribution_score: number;
  evidence_details?: Record<string, any>;
  created_at: string;
}

export interface EquipmentPredictionItem {
  id: string;
  organization_id: string;
  machine_id: string;
  component_id?: string | null;
  failure_mode_id: string;
  failure_mode_name?: string | null;
  failure_mode_code?: string | null;
  model_version_id?: string | null;
  prediction_horizon_hours: number;
  status: string;
  calibrated_probability: number | null;
  uncalibrated_score: number | null;
  risk_category: PredictiveRiskCategory;
  rul_hours: number | null;
  rul_confidence_lower: number | null;
  rul_confidence_upper: number | null;
  rul_method?: string | null;
  rationale: string;
  evaluated_at: string;
  created_at: string;
  evidence?: PredictionEvidenceItem[];
}

export interface PredictiveAlertItem {
  id: string;
  organization_id: string;
  machine_id: string;
  machine_name: string;
  component_id?: string | null;
  failure_mode_id: string;
  failure_mode_name: string;
  prediction_id: string;
  prediction_horizon_hours: number;
  calibrated_risk: number;
  risk_category: PredictiveRiskCategory;
  status: PredictiveAlertStatus;
  engineer_review_notes?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  first_detected_at: string;
  last_detected_at: string;
  created_at: string;
}

export interface PredictiveModelVersionItem {
  id: string;
  registry_id: string;
  version_number: number;
  algorithm: string;
  prediction_horizon_hours: number;
  feature_schema: any;
  hyperparameters: any;
  training_sample_count: number;
  positive_sample_count: number;
  validation_metrics: {
    precision?: number;
    recall?: number;
    f1?: number;
    roc_auc?: number;
    pr_auc?: number;
    false_alarm_rate?: number;
    confusion_matrix?: Record<string, number>;
  };
  calibration_metrics: {
    brier_score?: number;
    ece?: number;
    is_well_calibrated?: boolean;
    reliability_bins?: Array<{ bin_predicted: number; bin_actual: number }>;
  };
  is_calibrated: boolean;
  status: string;
  created_by?: string;
  approved_by?: string;
  approved_at?: string;
  created_at: string;
}

export interface PredictiveModelRegistryItem {
  id: string;
  organization_id: string;
  machine_id: string;
  component_id?: string | null;
  failure_mode_id: string;
  failure_mode_name?: string | null;
  name: string;
  model_type: string;
  prediction_horizon_hours: number;
  lifecycle_status: string;
  active_version_number?: number | null;
  created_at: string;
  updated_at: string;
  versions?: PredictiveModelVersionItem[];
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    const url = `${this.baseUrl}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    };

    if (typeof window !== 'undefined') {
      const storedToken = localStorage.getItem('pharma_session_token');
      if (storedToken && !headers['Authorization']) {
        headers['Authorization'] = `Bearer ${storedToken}`;
      }
    }

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        credentials: 'include', // Automatically send and receive HttpOnly session cookies
      });

      const json = await response.json().catch(() => ({}));

      if (!response.ok) {
        return {
          error: json.message || json.error || `HTTP ${response.status}`,
          status: response.status,
        };
      }

      return {
        data: json as T,
        status: response.status,
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Network connection failed';
      return {
        error: message,
        status: 0,
      };
    }
  }

  /**
   * Check backend system health.
   */
  async getHealth(): Promise<ApiResponse<HealthResponse>> {
    return this.request<HealthResponse>('/health');
  }

  /**
   * User login with email and password.
   */
  async login(email: string, password: string): Promise<ApiResponse<LoginResponse>> {
    const res = await this.request<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (res.data?.session_token && typeof window !== 'undefined') {
      localStorage.setItem('pharma_session_token', res.data.session_token);
    }
    return res;
  }

  /**
   * User logout, revokes session.
   */
  async logout(): Promise<ApiResponse<{ message: string }>> {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('pharma_session_token');
    }
    return this.request<{ message: string }>('/auth/logout', {
      method: 'POST',
    });
  }

  /**
   * Retrieve current authenticated user profile and permissions.
   */
  async getMe(): Promise<ApiResponse<AuthMeResponse>> {
    return this.request<AuthMeResponse>('/auth/me');
  }

  /**
   * Retrieve current organization profile and site summary.
   */
  async getCurrentOrganization(): Promise<ApiResponse<{ organization: OrganizationDetails; sites: SiteDetails[] }>> {
    return this.request<{ organization: OrganizationDetails; sites: SiteDetails[] }>('/organizations/current');
  }

  /**
   * List manufacturing sites for user's organization.
   */
  async getSites(): Promise<ApiResponse<{ sites: SiteDetails[]; count: number }>> {
    return this.request<{ sites: SiteDetails[]; count: number }>('/sites');
  }

  /**
   * List team members in current organization.
   */
  async getUsers(): Promise<ApiResponse<{ users: UserProfile[]; count: number }>> {
    return this.request<{ users: UserProfile[]; count: number }>('/users');
  }

  /**
   * Invite a new user to the organization.
   */
  async inviteUser(email: string, roleName: string): Promise<ApiResponse<{ message: string; invitation: unknown }>> {
    return this.request<{ message: string; invitation: unknown }>('/users/invite', {
      method: 'POST',
      body: JSON.stringify({ email, role_name: roleName }),
    });
  }

  /**
   * Seed demo data (for development & demo verification).
   */
  async seedDemoData(): Promise<ApiResponse<{ message: string; seeded: unknown }>> {
    return this.request<{ message: string; seeded: unknown }>('/auth/seed', {
      method: 'POST',
    });
  }

  /**
   * Submit demonstration request.
   */
  async submitDemoRequest(payload: DemoRequestPayload): Promise<ApiResponse<{ received: boolean }>> {
    return this.request<{ received: boolean }>('/demo-requests', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // ============================================================================
  // PHASE 3: UNIVERSAL EQUIPMENT REGISTRY METHODS
  // ============================================================================

  /**
   * Retrieve list of equipment with optional filters and pagination.
   */
  async getEquipment(params: {
    site_id?: string;
    production_area_id?: string;
    production_line_id?: string;
    category_id?: string;
    criticality?: string;
    lifecycle_status?: string;
    connection_status?: string;
    search?: string;
    page?: number;
    per_page?: number;
    sort_by?: string;
    sort_order?: string;
  } = {}): Promise<ApiResponse<{ equipment: EquipmentItem[]; pagination: { page: number; per_page: number; total: number; pages: number } }>> {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, val]) => {
      if (val !== undefined && val !== null && val !== '') {
        query.append(key, String(val));
      }
    });
    const queryString = query.toString();
    return this.request(`/equipment${queryString ? `?${queryString}` : ''}`);
  }

  /**
   * Retrieve live equipment summary metrics.
   */
  async getEquipmentSummary(): Promise<ApiResponse<EquipmentSummary>> {
    return this.request<EquipmentSummary>('/equipment/summary');
  }

  /**
   * Retrieve single equipment record with technical details and relationships.
   */
  async getEquipmentDetail(id: string): Promise<ApiResponse<{ equipment: EquipmentItem }>> {
    return this.request<{ equipment: EquipmentItem }>(`/equipment/${id}`);
  }

  /**
   * Register a new machine in the equipment registry.
   */
  async createEquipment(data: CreateEquipmentPayload): Promise<ApiResponse<{ message: string; equipment: EquipmentItem }>> {
    return this.request<{ message: string; equipment: EquipmentItem }>('/equipment', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update equipment metadata (criticality, status, model, location).
   */
  async updateEquipment(id: string, data: UpdateEquipmentPayload): Promise<ApiResponse<{ message: string; equipment: EquipmentItem }>> {
    return this.request<{ message: string; equipment: EquipmentItem }>(`/equipment/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  /**
   * List equipment categories (defaults + custom organization categories).
   */
  async getCategories(): Promise<ApiResponse<{ categories: EquipmentCategoryItem[]; count: number }>> {
    return this.request<{ categories: EquipmentCategoryItem[]; count: number }>('/equipment/categories');
  }

  /**
   * Create a custom equipment category.
   */
  async createCategory(name: string, description?: string): Promise<ApiResponse<{ message: string; category: EquipmentCategoryItem }>> {
    return this.request<{ message: string; category: EquipmentCategoryItem }>('/equipment/categories', {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    });
  }

  /**
   * List components and subcomponents for an equipment asset.
   */
  async getComponents(machineId: string): Promise<ApiResponse<{ components: MachineComponentItem[]; count: number }>> {
    return this.request<{ components: MachineComponentItem[]; count: number }>(`/equipment/${machineId}/components`);
  }

  /**
   * Add a component to an equipment asset.
   */
  async addComponent(machineId: string, data: CreateComponentPayload): Promise<ApiResponse<{ message: string; component: MachineComponentItem }>> {
    return this.request<{ message: string; component: MachineComponentItem }>(`/equipment/${machineId}/components`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update a component (supports hierarchical reparenting with cycle detection).
   */
  async updateComponent(componentId: string, data: UpdateComponentPayload): Promise<ApiResponse<{ message: string; component: MachineComponentItem }>> {
    return this.request<{ message: string; component: MachineComponentItem }>(`/equipment/components/${componentId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  /**
   * List production areas belonging to user's organization (optionally filtered by site).
   */
  async getProductionAreas(siteId?: string): Promise<ApiResponse<{ production_areas: ProductionAreaItem[]; count: number }>> {
    const query = siteId ? `?site_id=${encodeURIComponent(siteId)}` : '';
    return this.request<{ production_areas: ProductionAreaItem[]; count: number }>(`/production-areas${query}`);
  }

  /**
   * Create a new production area.
   */
  async createProductionArea(data: CreateProductionAreaPayload): Promise<ApiResponse<{ message: string; production_area: ProductionAreaItem }>> {
    return this.request<{ message: string; production_area: ProductionAreaItem }>('/production-areas', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * List manufacturing production lines (optionally filtered by site and/or area).
   */
  async getProductionLines(params: { site_id?: string; production_area_id?: string } = {}): Promise<ApiResponse<{ production_lines: ProductionLineItem[]; count: number }>> {
    const query = new URLSearchParams();
    if (params.site_id) query.append('site_id', params.site_id);
    if (params.production_area_id) query.append('production_area_id', params.production_area_id);
    const queryString = query.toString();
    return this.request<{ production_lines: ProductionLineItem[]; count: number }>(`/production-lines${queryString ? `?${queryString}` : ''}`);
  }

  /**
   * Create a new production line.
   */
  async createProductionLine(data: CreateProductionLinePayload): Promise<ApiResponse<{ message: string; production_line: ProductionLineItem }>> {
    return this.request<{ message: string; production_line: ProductionLineItem }>('/production-lines', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // ============================================================================
  // PHASE 4, STEP 5: AUTOMATIC OPC UA TAG DISCOVERY METHODS
  // ============================================================================

  /**
   * Discover available OPC UA tags for a machine.
   */
  async getDiscoveredTags(
    machineId: string,
    params: { endpoint_url?: string; parent_node_id?: string; depth?: number; max_nodes?: number } = {}
  ): Promise<ApiResponse<{ machine_id: string; count: number; tags: DiscoveredTag[] }>> {
    const query = new URLSearchParams();
    if (params.endpoint_url) query.append('endpoint_url', params.endpoint_url);
    if (params.parent_node_id) query.append('parent_node_id', params.parent_node_id);
    if (params.depth) query.append('depth', String(params.depth));
    if (params.max_nodes) query.append('max_nodes', String(params.max_nodes));
    const qs = query.toString();
    return this.request(`/connectivity/tags/${machineId}${qs ? `?${qs}` : ''}`);
  }

  /**
   * Retrieve metadata for a specific NodeId.
   */
  async getTagMetadata(
    machineId: string,
    nodeId: string,
    endpointUrl?: string
  ): Promise<ApiResponse<{ metadata: DiscoveredTag }>> {
    const query = new URLSearchParams({ node_id: nodeId });
    if (endpointUrl) query.append('endpoint_url', endpointUrl);
    return this.request(`/connectivity/tags/${machineId}/metadata?${query.toString()}`);
  }

  /**
   * Search address space tags for matching signals.
   */
  async searchTags(
    machineId: string,
    searchQuery: string,
    endpointUrl?: string
  ): Promise<ApiResponse<{ machine_id: string; query: string; count: number; tags: DiscoveredTag[] }>> {
    return this.request(`/connectivity/tags/${machineId}/search`, {
      method: 'POST',
      body: JSON.stringify({ query: searchQuery, endpoint_url: endpointUrl }),
    });
  }

  // ============================================================================
  // PHASE 4, STEP 6: SIGNAL MAPPING & VALIDATION METHODS
  // ============================================================================

  /**
   * Fetch signal definitions catalog (standard + custom).
   */
  async getSignalDefinitions(group?: string): Promise<ApiResponse<{ count: number; definitions: SignalDefinitionItem[] }>> {
    const query = group ? `?group=${encodeURIComponent(group)}` : '';
    return this.request(`/signals/definitions${query}`);
  }

  /**
   * Create custom signal definition for organization.
   */
  async createCustomSignalDefinition(
    data: Partial<SignalDefinitionItem>
  ): Promise<ApiResponse<{ message: string; definition: SignalDefinitionItem }>> {
    return this.request('/signals/definitions', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * List mapped signals for a machine.
   */
  async getMachineSignals(
    machineId: string
  ): Promise<ApiResponse<{ machine_id: string; count: number; signals: MachineSignalItem[] }>> {
    return this.request(`/equipment/${machineId}/signals`);
  }

  /**
   * Create single or batch signal mappings for a machine.
   */
  async createMachineSignals(
    machineId: string,
    signals: CreateSignalPayload | CreateSignalPayload[]
  ): Promise<ApiResponse<{ message: string; count: number; signals: MachineSignalItem[] }>> {
    const payload = Array.isArray(signals) ? { signals } : signals;
    return this.request(`/equipment/${machineId}/signals`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  /**
   * Update signal mapping properties (increments mapping_version, resets status to PENDING).
   */
  async updateMachineSignal(
    machineId: string,
    signalId: string,
    data: UpdateSignalPayload
  ): Promise<ApiResponse<{ message: string; signal: MachineSignalItem }>> {
    return this.request(`/equipment/${machineId}/signals/${signalId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  /**
   * Delete a signal mapping.
   */
  async deleteMachineSignal(
    machineId: string,
    signalId: string
  ): Promise<ApiResponse<{ message: string }>> {
    return this.request(`/equipment/${machineId}/signals/${signalId}`, {
      method: 'DELETE',
    });
  }

  /**
   * Run 7-check validation engine against machine signals. Strictly read-only.
   */
  async validateMachineSignals(
    machineId: string,
    options?: { signal_ids?: string[]; endpoint_url?: string }
  ): Promise<ApiResponse<{ machine_id: string; count: number; results: SignalValidationResultItem[]; summary: MappingSummary }>> {
    return this.request(`/equipment/${machineId}/signals/validate`, {
      method: 'POST',
      body: JSON.stringify(options || {}),
    });
  }

  /**
   * Get validation results history for a machine.
   */
  async getMachineValidationResults(
    machineId: string
  ): Promise<ApiResponse<{ machine_id: string; count: number; results: SignalValidationResultItem[] }>> {
    return this.request(`/equipment/${machineId}/signals/validation-results`);
  }

  /**
   * Get high-level mapping summary and readiness for monitoring.
   */
  async getMachineMappingSummary(
    machineId: string
  ): Promise<ApiResponse<MappingSummary>> {
    return this.request(`/equipment/${machineId}/signals/mapping-summary`);
  }

  /**
   * Activate continuous OPC UA monitoring session for a machine.
   */
  async activateMonitoring(
    machineId: string,
    endpointUrl?: string
  ): Promise<ApiResponse<{ message: string; session: MonitoringSessionItem }>> {
    return this.request(`/equipment/${machineId}/monitoring/activate`, {
      method: 'POST',
      body: JSON.stringify({ endpoint_url: endpointUrl }),
    });
  }

  /**
   * Deactivate monitoring session for a machine.
   */
  async deactivateMonitoring(
    machineId: string
  ): Promise<ApiResponse<{ message: string; session: MonitoringSessionItem }>> {
    return this.request(`/equipment/${machineId}/monitoring/deactivate`, {
      method: 'POST',
    });
  }

  /**
   * Get monitoring lifecycle status, desired vs observed states, buffer metrics.
   */
  async getMonitoringStatus(
    machineId: string
  ): Promise<ApiResponse<MonitoringStatusResponse>> {
    return this.request(`/equipment/${machineId}/monitoring/status`);
  }

  /**
   * Get latest normalized reading and freshness for all mapped signals on a machine.
   */
  async getLatestReadings(
    machineId: string
  ): Promise<ApiResponse<{ machine_id: string; count: number; readings: SignalReadingItem[]; simulator_flag: boolean }>> {
    return this.request(`/equipment/${machineId}/readings/latest`);
  }

  /**
   * Get historical time-series readings for trending charts with optional downsampling and multi-signal filtering.
   */
  async getHistoricalReadings(
    machineId: string,
    options?: {
      signal_id?: string;
      signal_ids?: string[];
      start_time?: string;
      end_time?: string;
      limit?: number;
      downsample?: boolean | string;
      bucket_seconds?: number;
    }
  ): Promise<ApiResponse<HistoricalReadingsResponse>> {
    const params = new URLSearchParams();
    if (options?.signal_id) params.set('signal_id', options.signal_id);
    if (options?.signal_ids && options.signal_ids.length > 0) {
      params.set('signal_ids', options.signal_ids.join(','));
    }
    if (options?.start_time) params.set('start_time', options.start_time);
    if (options?.end_time) params.set('end_time', options.end_time);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.downsample !== undefined) params.set('downsample', String(options.downsample));
    if (options?.bucket_seconds !== undefined) params.set('bucket_seconds', String(options.bucket_seconds));

    const qs = params.toString() ? `?${params.toString()}` : '';
    return this.request(`/equipment/${machineId}/readings/history${qs}`);
  }

  /**
   * Get configured warning and critical thresholds for an equipment asset.
   */
  async getEquipmentThresholds(
    machineId: string
  ): Promise<ApiResponse<EquipmentThresholdsResponse>> {
    return this.request(`/equipment/${machineId}/signals/thresholds`);
  }

  /**
   * Set or update operational warning/critical thresholds for an equipment signal.
   */
  async setSignalThreshold(
    machineId: string,
    signalId: string,
    payload: {
      warning_min?: number | null;
      warning_max?: number | null;
      critical_min?: number | null;
      critical_max?: number | null;
      unit?: string | null;
      notes?: string | null;
      is_active?: boolean;
    }
  ): Promise<ApiResponse<any>> {
    return this.request(`/equipment/${machineId}/signals/${signalId}/thresholds`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  /**
   * Get URL for historical telemetry export with filters.
   */
  getTelemetryExportUrl(
    machineId: string,
    options?: {
      format?: 'csv' | 'json';
      signal_ids?: string[];
      start_time?: string;
      end_time?: string;
      limit?: number;
    }
  ): string {
    const params = new URLSearchParams();
    if (options?.format) params.set('format', options.format);
    if (options?.signal_ids && options.signal_ids.length > 0) {
      params.set('signal_ids', options.signal_ids.join(','));
    }
    if (options?.start_time) params.set('start_time', options.start_time);
    if (options?.end_time) params.set('end_time', options.end_time);
    if (options?.limit) params.set('limit', String(options.limit));
    const qs = params.toString() ? `?${params.toString()}` : '';
    return `${this.baseUrl}/equipment/${machineId}/readings/export${qs}`;
  }

  /**
   * Export historical telemetry in CSV or JSON format.
   */
  async exportTelemetry(
    machineId: string,
    options?: {
      format?: 'csv' | 'json';
      signal_ids?: string[];
      start_time?: string;
      end_time?: string;
      limit?: number;
    }
  ): Promise<{ data?: string | any; filename?: string; error?: string }> {
    const format = options?.format || 'csv';
    const url = this.getTelemetryExportUrl(machineId, options);
    try {
      const headers: Record<string, string> = {};
      if (typeof window !== 'undefined') {
        const storedToken = localStorage.getItem('pharma_session_token');
        if (storedToken) {
          headers['Authorization'] = `Bearer ${storedToken}`;
        }
      }

      const res = await fetch(url, { headers, credentials: 'include' });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        return { error: (errJson as any).message || `Export failed: ${res.statusText}` };
      }

      if (format === 'json') {
        const json = await res.json();
        return { data: json, filename: `telemetry_${machineId}.json` };
      } else {
        const text = await res.text();
        const disposition = res.headers.get('content-disposition');
        let filename = `telemetry_${machineId}.csv`;
        if (disposition && disposition.includes('filename=')) {
          const match = disposition.match(/filename="?([^"]+)"?/);
          if (match && match[1]) filename = match[1];
        }
        return { data: text, filename };
      }
    } catch (err: any) {
      return { error: err.message || 'Export failed' };
    }
  }

  /**
   * Get storage health, telemetry volume and growth rates.
   */
  async getStorageHealth(): Promise<ApiResponse<any>> {
    return this.request('/monitoring/storage/health');
  }

  // ===========================================================================
  // PHASE 3 STEP 3.3: PLANT-WIDE OBSERVABILITY & FLEET MONITORING METHODS
  // ===========================================================================

  /**
   * Get plant-wide fleet KPI overview (total, monitoring, healthy, warning, critical, offline, stale, alarms).
   */
  async getFleetOverview(): Promise<ApiResponse<FleetOverviewResponse>> {
    return this.request('/monitoring/fleet/overview');
  }

  /**
   * Get searchable, filterable, and paginated equipment fleet monitoring list.
   */
  async getFleetMachines(options?: {
    site_id?: string;
    category_id?: string;
    status?: string;
    search?: string;
    sort_by?: string;
    order?: 'asc' | 'desc';
    page?: number;
    per_page?: number;
  }): Promise<ApiResponse<FleetMachinesResponse>> {
    const params = new URLSearchParams();
    if (options?.site_id) params.set('site_id', options.site_id);
    if (options?.category_id) params.set('category_id', options.category_id);
    if (options?.status) params.set('status', options.status);
    if (options?.search) params.set('search', options.search);
    if (options?.sort_by) params.set('sort_by', options.sort_by);
    if (options?.order) params.set('order', options.order);
    if (options?.page) params.set('page', String(options.page));
    if (options?.per_page) params.set('per_page', String(options.per_page));

    const qs = params.toString() ? `?${params.toString()}` : '';
    return this.request(`/monitoring/fleet${qs}`);
  }

  /**
   * Get centralized plant-wide equipment alerts.
   */
  async getFleetAlerts(options?: {
    status?: string;
    severity?: string;
    machine_id?: string;
    limit?: number;
  }): Promise<ApiResponse<FleetAlertsResponse>> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.severity) params.set('severity', options.severity);
    if (options?.machine_id) params.set('machine_id', options.machine_id);
    if (options?.limit) params.set('limit', String(options.limit));

    const qs = params.toString() ? `?${params.toString()}` : '';
    return this.request(`/monitoring/fleet/alerts${qs}`);
  }

  /**
   * Acknowledge a fleet alarm through authorized user action.
   */
  async acknowledgeFleetAlert(
    alertId: string,
    notes?: string
  ): Promise<ApiResponse<{ message: string; alert: any }>> {
    return this.request(`/monitoring/fleet/alerts/${alertId}/acknowledge`, {
      method: 'POST',
      body: JSON.stringify({ notes }),
    });
  }

  /**
   * Get effective telemetry retention policy for an equipment asset.
   */
  async getRetentionPolicy(machineId: string): Promise<ApiResponse<any>> {
    return this.request(`/equipment/${machineId}/retention/policy`);
  }

  /**
   * Set or update telemetry retention policy for an equipment asset.
   */
  async setRetentionPolicy(machineId: string, policy: any): Promise<ApiResponse<any>> {
    return this.request(`/equipment/${machineId}/retention/policy`, {
      method: 'POST',
      body: JSON.stringify(policy),
    });
  }

  /**
   * Execute retention cycle (supports dry_run preview).
   */
  async executeRetentionJob(
    machineId: string,
    options?: { dry_run?: boolean; batch_size?: number; max_batches?: number }
  ): Promise<ApiResponse<any>> {
    return this.request(`/equipment/${machineId}/retention/execute`, {
      method: 'POST',
      body: JSON.stringify(options || {}),
    });
  }

  /**
   * Get retention execution audit history for an equipment asset.
   */
  async getRetentionHistory(machineId: string, limit: number = 20): Promise<ApiResponse<any>> {
    return this.request(`/equipment/${machineId}/retention/history?limit=${limit}`);
  }

  /**
   * Get edge gateway health, buffer metrics and connection state.
   */
  async getGatewayHealth(
    gatewayId: string = 'gw-default'
  ): Promise<ApiResponse<GatewayHealthResponse>> {
    return this.request(`/gateways/${gatewayId}/health`);
  }

  // ===========================================================================
  // PHASE 5: CONDITION MONITORING, BASELINES & ANOMALY DETECTION METHODS
  // ===========================================================================

  /**
   * Get equipment data quality evaluation and issues.
   */
  async getDataQuality(
    machineId: string,
    recentMinutes: number = 15
  ): Promise<ApiResponse<DataQualityReport>> {
    return this.request(`/equipment/${machineId}/data-quality?recent_minutes=${recentMinutes}`);
  }

  /**
   * Get equipment operating context and classification confidence.
   */
  async getOperatingContext(
    machineId: string,
    recentMinutes: number = 15
  ): Promise<ApiResponse<OperatingContextResponse>> {
    return this.request(`/equipment/${machineId}/operating-context?recent_minutes=${recentMinutes}`);
  }

  /**
   * Get baseline profiles and active envelope statistics.
   */
  async getBaselines(
    machineId: string
  ): Promise<ApiResponse<{ profiles: BaselineProfileItem[]; count: number }>> {
    return this.request(`/equipment/${machineId}/baselines`);
  }

  /**
   * Build candidate baseline profiles from historical clean data.
   */
  async buildBaselines(
    machineId: string,
    options?: { lookback_days?: number; operating_state?: string }
  ): Promise<ApiResponse<{ message: string; results: any[] }>> {
    return this.request(`/equipment/${machineId}/baselines/build`, {
      method: 'POST',
      body: JSON.stringify(options || {}),
    });
  }

  /**
   * Approve and activate a baseline version.
   */
  async approveBaseline(
    versionId: string,
    notes?: string
  ): Promise<ApiResponse<{ message: string; version: any }>> {
    return this.request(`/baselines/${versionId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ notes }),
    });
  }

  /**
   * Get overall condition monitoring indicators and active anomalies.
   */
  async getConditionSummary(
    machineId: string
  ): Promise<ApiResponse<ConditionSummaryResponse>> {
    return this.request(`/equipment/${machineId}/condition`);
  }

  /**
   * Trigger on-demand condition and anomaly evaluation.
   */
  async evaluateCondition(
    machineId: string,
    recentMinutes: number = 15
  ): Promise<ApiResponse<{ message: string; evaluation: any }>> {
    return this.request(`/equipment/${machineId}/condition/evaluate`, {
      method: 'POST',
      body: JSON.stringify({ recent_minutes: recentMinutes }),
    });
  }

  /**
   * Get equipment anomalies with explainable evidence.
   */
  async getAnomalies(
    machineId: string,
    params?: { severity?: string; status?: string; limit?: number }
  ): Promise<ApiResponse<{ anomalies: AnomalyEventItem[]; count: number }>> {
    const qs = new URLSearchParams();
    if (params?.severity) qs.set('severity', params.severity);
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    const qStr = qs.toString() ? `?${qs.toString()}` : '';
    return this.request(`/equipment/${machineId}/anomalies${qStr}`);
  }

  /**
   * Get anomaly event detail with full evidence breakdown.
   */
  async getAnomalyDetail(
    anomalyId: string
  ): Promise<ApiResponse<{ anomaly: AnomalyEventItem }>> {
    return this.request(`/anomalies/${anomalyId}`);
  }

  /**
   * Get organization alerts.
   */
  async getAlerts(
    params?: { machine_id?: string; status?: string; severity?: string; limit?: number }
  ): Promise<ApiResponse<{ alerts: EquipmentAlertItem[]; count: number }>> {
    const qs = new URLSearchParams();
    if (params?.machine_id) qs.set('machine_id', params.machine_id);
    if (params?.status) qs.set('status', params.status);
    if (params?.severity) qs.set('severity', params.severity);
    if (params?.limit) qs.set('limit', String(params.limit));
    const qStr = qs.toString() ? `?${qs.toString()}` : '';
    return this.request(`/alerts${qStr}`);
  }

  /**
   * Acknowledge an equipment alert.
   */
  async acknowledgeAlert(
    alertId: string,
    notes?: string
  ): Promise<ApiResponse<{ message: string; alert: EquipmentAlertItem }>> {
    return this.request(`/alerts/${alertId}/acknowledge`, {
      method: 'POST',
      body: JSON.stringify({ notes }),
    });
  }

  /**
   * Update alert status with audit trail notes.
   */
  async updateAlertStatus(
    alertId: string,
    status: AlertStatus,
    notes?: string
  ): Promise<ApiResponse<{ message: string; alert: EquipmentAlertItem }>> {
    return this.request(`/alerts/${alertId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status, notes }),
    });
  }

  /**
   * Train multivariate Isolation Forest ML model.
   */
  async trainMLModel(
    machineId: string,
    lookbackDays: number = 7
  ): Promise<ApiResponse<{ message: string; result: any }>> {
    return this.request(`/equipment/${machineId}/ml-models/train`, {
      method: 'POST',
      body: JSON.stringify({ lookback_days: lookbackDays }),
    });
  }

  /**
   * Get ML models for machine.
   */
  async getMLModels(
    machineId: string
  ): Promise<ApiResponse<MLModelRegistryItem>> {
    return this.request(`/equipment/${machineId}/ml-models`);
  }

  // ==========================================================================
  // PHASE 6: FAILURE PREDICTION & PREDICTIVE MAINTENANCE APIS
  // ==========================================================================

  /**
   * Get failure modes catalog.
   */
  async getFailureModes(categoryId?: string): Promise<ApiResponse<FailureModeItem[]>> {
    const q = categoryId ? `?category_id=${categoryId}` : '';
    return this.request(`/failure-modes${q}`);
  }

  /**
   * Create custom failure mode for organization.
   */
  async createFailureMode(data: Partial<FailureModeItem>): Promise<ApiResponse<FailureModeItem>> {
    return this.request('/failure-modes', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * List equipment failure records.
   */
  async getEquipmentFailureRecords(
    machineId: string,
    limit: number = 100
  ): Promise<ApiResponse<FailureRecordItem[]>> {
    return this.request(`/equipment/${machineId}/failure-records?limit=${limit}`);
  }

  /**
   * Log failure or maintenance record.
   */
  async createFailureRecord(
    machineId: string,
    data: {
      failure_mode_id?: string;
      component_id?: string;
      failure_started_at: string;
      failure_description: string;
      observed_symptoms?: string[];
      confirmed_root_cause?: string;
      maintenance_action?: string;
      downtime_minutes?: number;
      verification_status?: FailureVerificationStatus;
    }
  ): Promise<ApiResponse<FailureRecordItem>> {
    return this.request(`/equipment/${machineId}/failure-records`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Update failure record verification status.
   */
  async verifyFailureRecord(
    recordId: string,
    data: {
      verification_status: FailureVerificationStatus;
      confirmed_root_cause?: string;
      maintenance_action?: string;
    }
  ): Promise<ApiResponse<FailureRecordItem>> {
    return this.request(`/failure-records/${recordId}/verify`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  /**
   * Get equipment predictive modeling eligibility.
   */
  async getEquipmentPredictionEligibility(
    machineId: string
  ): Promise<ApiResponse<PredictionEligibilityResponse>> {
    return this.request(`/equipment/${machineId}/prediction-eligibility`);
  }

  /**
   * Train supervised predictive model.
   */
  async trainPredictiveModel(
    machineId: string,
    data: {
      failure_mode_id: string;
      algorithm?: string;
      prediction_horizon_hours?: number;
      hyperparameters?: Record<string, any>;
    }
  ): Promise<ApiResponse<{
    registry: PredictiveModelRegistryItem;
    version: PredictiveModelVersionItem;
    training_summary: any;
  }>> {
    return this.request(`/equipment/${machineId}/predictive-models/train`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * List predictive models and versions for equipment.
   */
  async getEquipmentPredictiveModels(
    machineId: string
  ): Promise<ApiResponse<PredictiveModelRegistryItem[]>> {
    return this.request(`/equipment/${machineId}/predictive-models`);
  }

  /**
   * Approve a trained predictive model version.
   */
  async approvePredictiveModel(
    versionId: string
  ): Promise<ApiResponse<PredictiveModelVersionItem>> {
    return this.request(`/predictive-models/${versionId}/approve`, {
      method: 'POST',
    });
  }

  /**
   * Activate an approved model version for live prediction inference.
   */
  async activatePredictiveModel(
    versionId: string
  ): Promise<ApiResponse<{
    registry: PredictiveModelRegistryItem;
    active_version: PredictiveModelVersionItem;
  }>> {
    return this.request(`/predictive-models/${versionId}/activate`, {
      method: 'POST',
    });
  }

  /**
   * Trigger on-demand prediction and RUL evaluation.
   */
  async evaluateEquipmentPredictions(
    machineId: string
  ): Promise<ApiResponse<{
    message: string;
    predictions: EquipmentPredictionItem[];
  }>> {
    return this.request(`/equipment/${machineId}/predictions/evaluate`, {
      method: 'POST',
    });
  }

  /**
   * Get latest predictions and prediction history for equipment.
   */
  async getEquipmentPredictions(
    machineId: string,
    limit: number = 50
  ): Promise<ApiResponse<EquipmentPredictionItem[]>> {
    return this.request(`/equipment/${machineId}/predictions?limit=${limit}`);
  }

  /**
   * Get prediction detail with evidence attribution breakdown.
   */
  async getPredictionDetail(
    predictionId: string
  ): Promise<ApiResponse<EquipmentPredictionItem>> {
    return this.request(`/predictions/${predictionId}`);
  }

  /**
   * List predictive maintenance alerts.
   */
  async getPredictiveAlerts(params?: {
    machineId?: string;
    status?: string;
    limit?: number;
  }): Promise<ApiResponse<PredictiveAlertItem[]>> {
    const searchParams = new URLSearchParams();
    if (params?.machineId) searchParams.append('machine_id', params.machineId);
    if (params?.status) searchParams.append('status', params.status);
    if (params?.limit) searchParams.append('limit', params.limit.toString());
    const query = searchParams.toString() ? `?${searchParams.toString()}` : '';
    return this.request(`/predictive-alerts${query}`);
  }

  /**
   * Review predictive alert (acknowledge, investigate, resolve, dismiss).
   */
  async reviewPredictiveAlert(
    alertId: string,
    data: {
      status: PredictiveAlertStatus;
      engineer_review_notes?: string;
    }
  ): Promise<ApiResponse<PredictiveAlertItem>> {
    return this.request(`/predictive-alerts/${alertId}/review`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // ===========================================================================
  // PHASE 7: LANGGRAPH MULTI-AGENT DIAGNOSTICS & RAG
  // ===========================================================================

  /**
   * Initiate a LangGraph multi-agent diagnostic run for an equipment asset.
   */
  async startDiagnosticSession(data: {
    machine_id: string;
    component_id?: string;
    trigger_type?: string;
    trigger_event_id?: string;
  }): Promise<ApiResponse<{
    session: DiagnosticSessionItem;
    agent_executions: AgentExecutionItem[];
    recommendations: MaintenanceRecommendationItem[];
    report: DiagnosticReportItem | null;
    evaluations: Record<string, unknown>[];
  }>> {
    return this.request('/diagnostics/start', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Get diagnostic session detail.
   */
  async getDiagnosticSession(sessionId: string): Promise<ApiResponse<{
    session: DiagnosticSessionItem;
    agent_executions: AgentExecutionItem[];
    recommendations: MaintenanceRecommendationItem[];
    report: DiagnosticReportItem | null;
    evaluations: Record<string, unknown>[];
  }>> {
    return this.request(`/diagnostics/${sessionId}`);
  }

  /**
   * Get diagnostic session polling status.
   */
  async getDiagnosticStatus(sessionId: string): Promise<ApiResponse<{
    id: string;
    status: string;
    current_stage: string;
    completed_at: string | null;
    error_message: string | null;
  }>> {
    return this.request(`/diagnostics/${sessionId}/status`);
  }

  /**
   * Get synthesized diagnostic report for a session.
   */
  async getDiagnosticReport(sessionId: string): Promise<ApiResponse<DiagnosticReportItem>> {
    return this.request(`/diagnostics/${sessionId}/report`);
  }

  /**
   * Get step-by-step traces for all 7 agents in a diagnostic session.
   */
  async getAgentExecutions(sessionId: string): Promise<ApiResponse<AgentExecutionItem[]>> {
    return this.request(`/diagnostics/${sessionId}/agent-executions`);
  }

  /**
   * Submit human engineer review for a diagnostic investigation.
   */
  async reviewDiagnosticSession(
    sessionId: string,
    data: { status: string; notes?: string }
  ): Promise<ApiResponse<DiagnosticSessionItem>> {
    return this.request(`/diagnostics/${sessionId}/review`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * List recent diagnostic sessions.
   */
  async listDiagnosticSessions(params?: {
    machine_id?: string;
    limit?: number;
  }): Promise<ApiResponse<DiagnosticSessionItem[]>> {
    const searchParams = new URLSearchParams();
    if (params?.machine_id) searchParams.append('machine_id', params.machine_id);
    if (params?.limit) searchParams.append('limit', params.limit.toString());
    const query = searchParams.toString() ? `?${searchParams.toString()}` : '';
    return this.request(`/diagnostics/sessions${query}`);
  }

  /**
   * List maintenance recommendations.
   */
  async listMaintenanceRecommendations(params?: {
    machine_id?: string;
    priority?: string;
    approval_status?: string;
    session_id?: string;
    limit?: number;
  }): Promise<ApiResponse<MaintenanceRecommendationItem[]>> {
    const searchParams = new URLSearchParams();
    if (params?.machine_id) searchParams.append('machine_id', params.machine_id);
    if (params?.priority) searchParams.append('priority', params.priority);
    if (params?.approval_status) searchParams.append('approval_status', params.approval_status);
    if (params?.session_id) searchParams.append('session_id', params.session_id);
    if (params?.limit) searchParams.append('limit', params.limit.toString());
    const query = searchParams.toString() ? `?${searchParams.toString()}` : '';
    return this.request(`/maintenance/recommendations${query}`);
  }

  /**
   * Get single recommendation details.
   */
  async getRecommendation(recId: string): Promise<ApiResponse<MaintenanceRecommendationItem>> {
    return this.request(`/maintenance/recommendations/${recId}`);
  }

  /**
   * Approve a maintenance recommendation and generate work order stub.
   */
  async approveRecommendation(
    recId: string,
    data?: { notes?: string; assigned_technician_id?: string; scheduled_for?: string }
  ): Promise<ApiResponse<MaintenanceRecommendationItem>> {
    return this.request(`/maintenance/recommendations/${recId}/approve`, {
      method: 'POST',
      body: JSON.stringify(data || {}),
    });
  }

  /**
   * Reject a maintenance recommendation with mandatory justification.
   */
  async rejectRecommendation(
    recId: string,
    data: { reason: string; notes?: string }
  ): Promise<ApiResponse<MaintenanceRecommendationItem>> {
    return this.request(`/maintenance/recommendations/${recId}/reject`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * List accessible SOPs and technical manuals.
   */
  async listKnowledgeDocuments(params?: {
    document_type?: string;
    machine_type?: string;
    limit?: number;
  }): Promise<ApiResponse<KnowledgeDocumentItem[]>> {
    const searchParams = new URLSearchParams();
    if (params?.document_type) searchParams.append('document_type', params.document_type);
    if (params?.machine_type) searchParams.append('machine_type', params.machine_type);
    if (params?.limit) searchParams.append('limit', params.limit.toString());
    const query = searchParams.toString() ? `?${searchParams.toString()}` : '';
    return this.request(`/knowledge/documents${query}`);
  }

  /**
   * Index and vectorize a new technical document.
   */
  async createKnowledgeDocument(data: {
    title: string;
    content: string;
    document_type?: string;
    machine_type?: string;
    component_type?: string;
    is_standard?: boolean;
    metadata?: Record<string, unknown>;
  }): Promise<ApiResponse<KnowledgeDocumentItem>> {
    return this.request('/knowledge/documents', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * Test semantic vector similarity retrieval against SOP database.
   */
  async testKnowledgeRetrieval(data: {
    query: string;
    machine_type?: string;
    component_type?: string;
    top_k?: number;
  }): Promise<ApiResponse<RetrievedChunkItem[]>> {
    return this.request('/knowledge/retrieve-test', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // ==========================================
  // PHASE 9: FACTORY PILOTS & REAL-WORLD VALIDATION
  // ==========================================

  async listPilots(siteId?: string, status?: string): Promise<ApiResponse<FactoryPilotItem[]>> {
    const params = new URLSearchParams();
    if (siteId) params.append('site_id', siteId);
    if (status) params.append('status', status);
    return this.request(`/pilots?${params.toString()}`);
  }

  async createPilot(data: Partial<FactoryPilotItem>): Promise<ApiResponse<FactoryPilotItem>> {
    return this.request('/pilots', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getPilot(pilotId: string): Promise<ApiResponse<FactoryPilotItem>> {
    return this.request(`/pilots/${pilotId}`);
  }

  async updatePilot(pilotId: string, data: Partial<FactoryPilotItem>): Promise<ApiResponse<FactoryPilotItem>> {
    return this.request(`/pilots/${pilotId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async assignPilotEquipment(pilotId: string, machineIds: string[], monitoringMode: string = 'SHADOW'): Promise<ApiResponse<PilotEquipmentItem[]>> {
    return this.request(`/pilots/${pilotId}/equipment`, {
      method: 'POST',
      body: JSON.stringify({ machine_ids: machineIds, monitoring_mode: monitoringMode }),
    });
  }

  async performReadinessReview(pilotId: string): Promise<ApiResponse<Record<string, unknown>>> {
    return this.request(`/pilots/${pilotId}/readiness-review`, {
      method: 'POST',
    });
  }

  async updateReadinessCheck(pilotId: string, checkId: string, status: string, evidenceSummary?: string): Promise<ApiResponse<PilotReadinessCheckItem>> {
    return this.request(`/pilots/${pilotId}/readiness-checks/${checkId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status, evidence_summary: evidenceSummary }),
    });
  }

  async submitPilotApproval(pilotId: string, approvalType: string, decision: string, comments?: string): Promise<ApiResponse<PilotApprovalItem>> {
    return this.request(`/pilots/${pilotId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approval_type: approvalType, decision, comments }),
    });
  }

  async activatePilot(pilotId: string): Promise<ApiResponse<Record<string, unknown>>> {
    return this.request(`/pilots/${pilotId}/activate`, {
      method: 'POST',
    });
  }

  async pausePilot(pilotId: string): Promise<ApiResponse<Record<string, unknown>>> {
    return this.request(`/pilots/${pilotId}/pause`, {
      method: 'POST',
    });
  }

  async completePilot(pilotId: string): Promise<ApiResponse<Record<string, unknown>>> {
    return this.request(`/pilots/${pilotId}/complete`, {
      method: 'POST',
    });
  }

  async submitEngineerFeedback(pilotId: string, data: Record<string, unknown>): Promise<ApiResponse<PilotEngineerFeedbackItem>> {
    return this.request(`/pilots/${pilotId}/feedback`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getPilotMetrics(pilotId: string): Promise<ApiResponse<PilotMetricsItem>> {
    return this.request(`/pilots/${pilotId}/metrics`);
  }

  async generatePilotReport(pilotId: string, reportType: string = 'FINAL_PILOT_REPORT'): Promise<ApiResponse<PilotReportItem>> {
    return this.request(`/pilots/${pilotId}/report`, {
      method: 'POST',
      body: JSON.stringify({ report_type: reportType }),
    });
  }

  // ==============================================================================
  // COMMISSIONING WORKFLOW METHODS (PHASE 9)
  // ==============================================================================

  async importCommissioningDiscovery(
    machineId: string,
    payload: any,
    sessionName?: string
  ): Promise<ApiResponse<{ message: string; session: CommissioningSessionItem }>> {
    const query = sessionName ? `?session_name=${encodeURIComponent(sessionName)}` : '';
    return this.request(`/equipment/${machineId}/commissioning/import${query}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getCommissioningSessions(
    machineId: string
  ): Promise<ApiResponse<{ machine_id: string; count: number; sessions: CommissioningSessionItem[] }>> {
    return this.request(`/equipment/${machineId}/commissioning/sessions`);
  }

  async getCommissioningSession(
    sessionId: string,
    includeCandidates: boolean = false
  ): Promise<ApiResponse<{ session: CommissioningSessionItem }>> {
    const query = includeCandidates ? '?include_candidates=true' : '';
    return this.request(`/commissioning/sessions/${sessionId}${query}`);
  }

  async getSessionCandidates(
    sessionId: string,
    params?: {
      category?: string;
      confidence?: string;
      status?: string;
      is_mapped?: boolean;
      search?: string;
    }
  ): Promise<ApiResponse<{ session_id: string; count: number; candidates: DiscoveredSignalCandidateItem[] }>> {
    const q = new URLSearchParams();
    if (params?.category) q.set('category', params.category);
    if (params?.confidence) q.set('confidence', params.confidence);
    if (params?.status) q.set('status', params.status);
    if (params?.is_mapped !== undefined) q.set('is_mapped', String(params.is_mapped));
    if (params?.search) q.set('search', params.search);
    const qs = q.toString() ? `?${q.toString()}` : '';
    return this.request(`/commissioning/sessions/${sessionId}/candidates${qs}`);
  }

  async getCandidateDetail(
    candidateId: string
  ): Promise<ApiResponse<{ candidate: DiscoveredSignalCandidateItem }>> {
    return this.request(`/commissioning/candidates/${candidateId}`);
  }

  async updateCandidateMapping(
    candidateId: string,
    data: Partial<DiscoveredSignalCandidateItem>
  ): Promise<ApiResponse<{ message: string; candidate: DiscoveredSignalCandidateItem }>> {
    return this.request(`/commissioning/candidates/${candidateId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async reviewCandidate(
    candidateId: string,
    decision: 'APPROVED' | 'REJECTED',
    reason?: string
  ): Promise<ApiResponse<{ message: string; candidate: DiscoveredSignalCandidateItem }>> {
    return this.request(`/commissioning/candidates/${candidateId}/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, reason }),
    });
  }

  async bulkReviewCandidates(
    sessionId: string,
    candidateIds: string[],
    decision: 'APPROVED' | 'REJECTED',
    reason?: string
  ): Promise<ApiResponse<{ message: string; result: any }>> {
    return this.request(`/commissioning/sessions/${sessionId}/bulk-review`, {
      method: 'POST',
      body: JSON.stringify({ candidate_ids: candidateIds, decision, reason }),
    });
  }

  async activateCommissioningSession(
    sessionId: string
  ): Promise<ApiResponse<{ message: string; activation: any }>> {
    return this.request(`/commissioning/sessions/${sessionId}/activate`, {
      method: 'POST',
    });
  }

  async rollbackCommissioningSession(
    sessionId: string,
    reason?: string
  ): Promise<ApiResponse<{ message: string; session: CommissioningSessionItem }>> {
    return this.request(`/commissioning/sessions/${sessionId}/rollback`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  }
}

// Phase 7 Type Definitions
export interface DiagnosticSessionItem {
  id: string;
  organization_id: string;
  machine_id: string;
  machine_name?: string;
  component_id?: string;
  trigger_type: string;
  trigger_event_id?: string;
  status: 'INITIALIZING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'STOPPED';
  current_stage: string;
  summary_headline?: string;
  error_message?: string;
  created_by?: string;
  started_at: string;
  completed_at?: string;
  created_at: string;
  has_report?: boolean;
  recommendation_count?: number;
}

export interface AgentExecutionItem {
  id: string;
  diagnostic_session_id: string;
  agent_name: string;
  status: string;
  execution_time_ms: number;
  output_payload?: Record<string, unknown>;
  error_details?: string;
  created_at: string;
}

export interface MaintenanceRecommendationItem {
  id: string;
  organization_id: string;
  diagnostic_session_id: string;
  machine_id: string;
  machine_name?: string;
  component_id?: string;
  title: string;
  suspected_issue: string;
  recommended_action: string;
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  supporting_evidence?: Record<string, unknown>;
  safety_requirements?: string[];
  compliance_state: 'ALLOWED_FOR_REVIEW' | 'REQUIRES_ADDITIONAL_APPROVAL' | 'BLOCKED';
  compliance_notes?: string;
  approval_status: 'DRAFT' | 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED' | 'NEEDS_INVESTIGATION' | 'CLOSED';
  engineer_notes?: string;
  work_order_reference?: string;
  reviewed_by?: string;
  reviewed_at?: string;
  created_at: string;
  approvals?: {
    id: string;
    user_id: string;
    user_name?: string;
    decision: string;
    comments?: string;
    work_order_reference?: string;
    created_at: string;
  }[];
}

export interface DiagnosticReportItem {
  id: string;
  organization_id: string;
  diagnostic_session_id: string;
  machine_id: string;
  machine_name?: string;
  report_title: string;
  title?: string;
  executive_summary: string;
  data_quality_assessment?: { is_reliable?: boolean; score?: number };
  condition_summary?: { summary?: string };
  predictive_results?: { summary?: string };
  root_cause_analysis?: { hypotheses?: string[] };
  maintenance_recommendations?: Record<string, unknown>[];
  safety_compliance_notes?: string[];
  technical_limitations?: string[];
  version_number?: number;
  generated_at?: string;
}

export interface KnowledgeDocumentItem {
  id: string;
  organization_id?: string;
  title: string;
  document_type: string;
  manufacturer?: string;
  model?: string;
  component_type?: string;
  version: string;
  approval_status: string;
  source_filename: string;
  is_standard: boolean;
  chunk_count: number;
  created_at: string;
}

export interface RetrievedChunkItem {
  document_id: string;
  title: string;
  document_type: string;
  chunk_index: number;
  content_excerpt: string;
  section?: string;
  page_number?: number;
  source_filename?: string;
  relevance_score: number;
  is_standard?: boolean;
}

export interface FactoryPilotItem {
  id: string;
  organization_id: string;
  site_id: string;
  pilot_name: string;
  description?: string;
  objectives?: string;
  status: 'DRAFT' | 'READINESS_REVIEW' | 'AWAITING_APPROVAL' | 'APPROVED' | 'READY' | 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'CANCELLED';
  monitoring_mode: 'SHADOW' | 'ADVISORY';
  evaluation_criteria?: Record<string, unknown>;
  target_kpis?: Record<string, unknown>;
  responsible_engineer_id?: string;
  planned_start_date?: string;
  planned_end_date?: string;
  actual_start_date?: string;
  actual_end_date?: string;
  equipment?: PilotEquipmentItem[];
  approvals?: PilotApprovalItem[];
  readiness_checks?: PilotReadinessCheckItem[];
  created_at: string;
  updated_at: string;
}

export interface PilotEquipmentItem {
  id: string;
  pilot_id: string;
  machine_id: string;
  machine_name?: string;
  asset_code?: string;
  monitoring_mode: string;
  readiness_status: string;
  is_active: boolean;
  assigned_at: string;
}

export interface PilotApprovalItem {
  id: string;
  pilot_id: string;
  approver_id: string;
  approver_name?: string;
  approval_type: string;
  decision: string;
  comments?: string;
  signature_hash: string;
  signed_at: string;
}

export interface PilotReadinessCheckItem {
  id: string;
  pilot_id: string;
  machine_id?: string;
  check_category: string;
  check_name: string;
  description?: string;
  status: string;
  evidence_summary?: string;
  reviewer_name?: string;
  reviewed_at?: string;
}

export interface PilotEngineerFeedbackItem {
  id: string;
  pilot_id: string;
  diagnostic_session_id: string;
  anomaly_event_id?: string;
  engineer_id: string;
  engineer_name?: string;
  assessment: string;
  verified_root_cause?: string;
  inspection_findings?: string;
  action_taken?: string;
  actual_outcome?: string;
  comments?: string;
  false_alarm_flag: boolean;
  reference_label: string;
  feedback_timestamp: string;
}

export interface PilotMetricsItem {
  pilot_id: string;
  pilot_name: string;
  status: string;
  monitoring_mode: string;
  total_feedback_submissions: number;
  accurate_feedback_count: number;
  accuracy_percentage: number;
  false_alarms_recorded: number;
  true_positives_recorded: number;
  anomaly_detection_precision: number;
  telemetry_ingestion_uptime_pct: number;
  safety_enforcement_adherence_pct: number;
  batch_disruptions_count: number;
  shadow_mode_integrity_verified: boolean;
}

export interface PilotReportItem {
  id: string;
  pilot_id: string;
  report_type: string;
  executive_summary: string;
  metrics_summary: Record<string, unknown>;
  findings_and_deviations?: string;
  go_no_go_recommendation: string;
  limitations_and_disclaimers?: string;
  generated_at: string;
}

// Phase 9 Commissioning Types
export interface CommissioningSessionItem {
  id: string;
  organization_id: string;
  machine_id: string;
  machine_name?: string;
  asset_code?: string;
  session_name: string;
  source_endpoint_url?: string;
  status: 'DISCOVERED' | 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED' | 'ACTIVATED' | 'CANCELLED';
  discovered_nodes_count: number;
  mapped_candidates_count: number;
  unmapped_candidates_count: number;
  approved_count: number;
  rejected_count: number;
  activated_count: number;
  metadata: Record<string, any>;
  audit_log: Array<{
    timestamp: string;
    user_id?: string;
    action: string;
    details?: string;
  }>;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
  activated_at?: string;
  activated_by?: string;
  candidates?: DiscoveredSignalCandidateItem[];
}

export interface DiscoveredSignalCandidateItem {
  id: string;
  session_id: string;
  organization_id: string;
  machine_id: string;
  source_node_id: string;
  browse_name?: string;
  display_name?: string;
  source_data_type?: string;
  access_level?: string;
  source_unit?: string;
  suggested_category?: string;
  confidence_level: 'HIGH' | 'MEDIUM' | 'LOW' | 'UNMAPPED';
  confidence_score: number;
  suggested_signal_code?: string;
  target_signal_definition_id?: string;
  signal_definition_code?: string;
  signal_definition_name?: string;
  custom_name?: string;
  component_id?: string;
  component_name?: string;
  engineering_unit?: string;
  scaling_factor: number;
  offset: number;
  sampling_interval_ms: number;
  warning_min?: number | null;
  warning_max?: number | null;
  critical_min?: number | null;
  critical_max?: number | null;
  is_mapped: boolean;
  status: 'DISCOVERED' | 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED' | 'ACTIVATED';
  registered_machine_signal_id?: string | null;
  review_history: Array<{
    timestamp: string;
    user_id?: string;
    user_email?: string;
    action?: string;
    previous_status?: string;
    new_status?: string;
    decision?: string;
    reason?: string;
    previous_mapping?: Record<string, any>;
    new_mapping?: Record<string, any>;
  }>;
  validation_errors: string[];
  validation_warnings: string[];
  is_valid: boolean;
  created_at?: string;
  updated_at?: string;
}

export const apiClient = new ApiClient(API_BASE_URL);
export default apiClient;

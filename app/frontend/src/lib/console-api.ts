/**
 * 控制台 API 封装层：统一通过 Atoms Web SDK 访问后端自定义 API。
 * 禁止 fetch / axios / 直连地址 —— 全部走 client.apiCall.invoke。
 */
import { client } from './api';

export interface InvokeErrorShape {
  detail?: string;
  message?: string;
}

/** 从 SDK 抛出的错误中提取后端 detail 信息。 */
export function errDetail(e: unknown): string {
  const err = e as { data?: InvokeErrorShape; response?: { data?: InvokeErrorShape }; message?: string };
  return (
    err?.data?.detail ||
    err?.response?.data?.detail ||
    err?.data?.message ||
    err?.response?.data?.message ||
    err?.message ||
    '请求失败，请稍后重试'
  );
}

async function invoke<T>(url: string, method: 'GET' | 'POST' | 'PUT' = 'GET', data?: unknown): Promise<T> {
  const res = await client.apiCall.invoke({ url, method, data });
  return res.data as T;
}

// ---------------- 类型定义 ----------------

export interface Permissions {
  user: { id: string; email: string | null; name: string | null };
  role: string;
  role_label: string;
  level: number;
  can_diagnose: boolean;
  can_feedback: boolean;
  can_edit_kb: boolean;
  can_approve: boolean;
  can_publish: boolean;
  can_manage_rules: boolean;
  can_manage_config: boolean;
  approval_mode: 'OFF' | 'SINGLE_REVIEW' | 'MULTI_LEVEL';
}

export interface DashboardData {
  metrics: {
    total_events: number;
    noise_reduction: number;
    unknown_rate: number;
    rag_success_rate: number;
    rag_p99_ms: number | null;
    avg_rag_ms: number | null;
  };
  by_severity: Record<string, number>;
  top_error_types: { name: string; count: number }[];
  top_services: { name: string; count: number }[];
  recent_events: {
    id: number;
    event_id: string;
    severity: string;
    service_name: string;
    error_type: string | null;
    status: string | null;
    created_at: string | null;
  }[];
  health: Record<string, { status: string; detail: string }>;
  kb: { total: number; archived: number; avg_feedback: number };
  todo: { pending_approvals: number; pending_unknowns: number };
}

export interface EventItem {
  id: number;
  event_id: string;
  severity: string;
  service_name: string;
  cluster: string | null;
  error_type: string | null;
  template: string | null;
  status: string | null;
  rag_status: string | null;
  rag_score: number | null;
  confidence: number | null;
  degraded_reason: string | null;
  created_at: string | null;
}

export interface EventDetail extends EventItem {
  raw_log: string | null;
  fingerprint: string | null;
  topology: string | null;
  rag_ms: number | null;
  std_ms: number | null;
  candidates: { case_id: string; error_type: string; service_name: string; score: number; root_cause: string | null; solution: string | null; feedback_score: number | null }[] | null;
  ai_root_cause: string | null;
  ai_solution: string | null;
  ai_command: string | null;
  ai_output: { root_cause: string; solution: string; confidence: number; command: string } | null;
}

export interface DiagnosisResult {
  status: string;
  message: string;
  event_id: number;
  rag: { status: string; score: number | null; ms: number; candidates: EventDetail['candidates'] };
  diagnosis: {
    root_cause: string;
    solution: string;
    confidence: number;
    command: string;
    model: string;
    low_confidence: boolean;
    threshold: number;
  } | null;
}

export interface Paged<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

export interface KbCase {
  id: number;
  case_id: string;
  error_type: string;
  service_name: string;
  cluster: string | null;
  alert_template: string | null;
  root_cause: string | null;
  solution: string | null;
  topology_snapshot: string | null;
  status: string | null;
  version: number | null;
  feedback_score: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CaseVersion {
  id: number;
  case_id: string;
  version: number;
  snapshot: Record<string, unknown> | null;
  approval_id: number | null;
  created_by: string | null;
  created_at: string | null;
}

export interface ChangeSet {
  id: number;
  case_id: string;
  change_type: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  diff: Record<string, { before: unknown; after: unknown }> | null;
  reason: string | null;
  status: string;
  version: number | null;
  approval_request_id: number | null;
  created_by: string | null;
  created_at: string | null;
}

export interface KbCaseDetail {
  case: KbCase;
  versions: CaseVersion[];
  change_sets: ChangeSet[];
}

export interface ApprovalStep {
  id: number;
  step_no: number;
  approver_role: string;
  approver_role_label: string;
  approver: string | null;
  action: string;
  comment: string | null;
  acted_at: string | null;
}

export interface ApprovalRequest {
  id: number;
  applicant: string;
  applicant_role: string;
  applicant_role_label: string;
  biz_type: string;
  biz_id: string;
  title: string;
  reason: string | null;
  risk_level: string | null;
  status: string;
  current_step: number;
  total_steps: number;
  published_at: string | null;
  steps: ApprovalStep[];
  created_at: string | null;
}

/** 审批关联业务内容：kb_edit 返回 ChangeSet（含 diff）、merge 返回提案、rule_promote 返回模板。 */
export type ApprovalBizContent = ChangeSet | MergeProposal | UnknownTemplate;

export interface ApprovalContentData {
  biz_type: string;
  biz_id: string;
  title: string;
  content: ApprovalBizContent | null;
}

export interface RuleVersion {
  id: number;
  version: number;
  content: string;
  status: string;
  change_note: string | null;
  created_by: string | null;
  created_at: string | null;
}

export interface RulesData {
  active: RuleVersion | null;
  versions: RuleVersion[];
  rule_count: number;
}

export interface UnknownTemplate {
  id: number;
  template: string;
  suggested_error_type: string | null;
  sample_count: number | null;
  last_seen_service: string | null;
  status: string;
  created_at: string | null;
}

export interface AuditLog {
  id: number;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string | null;
}

export interface ConfigItem {
  key: string;
  value: string;
  description: string;
  is_default: boolean;
}

export interface MergeGroup {
  error_type: string;
  service_name: string;
  case_ids: string[];
  cases: KbCase[];
  suggested_master: string;
}

export interface MergeProposal {
  id: number;
  master_case_id: string;
  merged_case_ids: string[];
  merge_strategy: Record<string, unknown> | null;
  reason: string | null;
  status: string;
  approval_request_id: number | null;
  created_by: string | null;
  created_at: string | null;
}

// ---------------- API 函数 ----------------

export const consoleApi = {
  getPermissions: () => invoke<Permissions>('/api/v1/console/permissions'),
  getDashboard: () => invoke<DashboardData>('/api/v1/console/dashboard'),

  listEvents: (params: Record<string, string | number>) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString();
    return invoke<Paged<EventItem>>(`/api/v1/console/events?${qs}`);
  },
  getEvent: (id: number) => invoke<EventDetail>(`/api/v1/console/events/${id}`),
  diagnose: (id: number) =>
    invoke<DiagnosisResult>(`/api/v1/console/events/${id}/diagnose`, 'POST', {}),
  feedback: (id: number, body: { rating: string; correction?: Record<string, string>; comment?: string }) =>
    invoke<{ case_id: string; feedback_score: number; rating: string; correction_change_set: unknown }>(
      `/api/v1/console/events/${id}/feedback`, 'POST', body,
    ),

  listKbCases: (params: Record<string, string | number>) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString();
    return invoke<Paged<KbCase>>(`/api/v1/console/kb/cases?${qs}`);
  },
  getKbCase: (caseId: string) => invoke<KbCaseDetail>(`/api/v1/console/kb/cases/${encodeURIComponent(caseId)}`),
  createChangeSet: (body: { case_id: string; change_type: string; fields: Record<string, string>; reason: string }) =>
    invoke<{ change_set: ChangeSet; approval_mode: string; auto_published: boolean; approval_request_id?: number }>(
      '/api/v1/console/kb/change-sets', 'POST', body,
    ),
  rollbackCase: (caseId: string, version: number) =>
    invoke<KbCase>(`/api/v1/console/kb/cases/${encodeURIComponent(caseId)}/rollback`, 'POST', { version }),
  scanDuplicates: () => invoke<{ groups: MergeGroup[] }>('/api/v1/console/kb/duplicates'),
  listMergeProposals: () => invoke<MergeProposal[]>('/api/v1/console/kb/merge-proposals'),
  createMergeProposal: (body: { master_case_id: string; merged_case_ids: string[]; reason: string }) =>
    invoke<{ proposal: MergeProposal; auto_merged: boolean; approval_request_id?: number }>(
      '/api/v1/console/kb/merge-proposals', 'POST', body,
    ),
  listChangeSets: (status?: string) =>
    invoke<Paged<ChangeSet>>(`/api/v1/console/change-sets${status ? `?status=${status}` : ''}`),

  listApprovals: (box: string) =>
    invoke<{ items: ApprovalRequest[]; role: string }>(`/api/v1/console/approvals?box=${box}`),
  decideApproval: (id: number, action: string, comment: string) =>
    invoke<{ status: string }>(`/api/v1/console/approvals/${id}/decide`, 'POST', { action, comment }),
  getApprovalContent: (id: number) =>
    invoke<ApprovalContentData>(`/api/v1/console/approvals/${id}/content`),

  getRules: () => invoke<RulesData>('/api/v1/console/rules'),
  validateRules: (content: string) =>
    invoke<{ valid: boolean; rule_count: number; rule_ids: string[] }>('/api/v1/console/rules/validate', 'POST', { content }),
  publishRules: (content: string, change_note: string) =>
    invoke<RuleVersion>('/api/v1/console/rules/publish', 'POST', { content, change_note }),
  rollbackRules: (versionId: number) =>
    invoke<RuleVersion>(`/api/v1/console/rules/${versionId}/rollback`, 'POST', {}),

  listUnknownTemplates: (status?: string) =>
    invoke<{ items: UnknownTemplate[] }>(`/api/v1/console/unknown-templates${status ? `?status=${status}` : ''}`),
  promoteTemplate: (id: number, errorType: string) =>
    invoke<{ template: UnknownTemplate; approval_request_id: number }>(
      `/api/v1/console/unknown-templates/${id}/promote`, 'POST', { error_type: errorType },
    ),
  discardTemplate: (id: number) =>
    invoke<UnknownTemplate>(`/api/v1/console/unknown-templates/${id}/discard`, 'POST', {}),

  listAuditLogs: (params: Record<string, string | number>) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString();
    return invoke<Paged<AuditLog>>(`/api/v1/console/audit-logs?${qs}`);
  },

  listConfigs: () => invoke<{ items: ConfigItem[] }>('/api/v1/console/configs'),
  updateConfig: (key: string, value: string) =>
    invoke<{ key: string; value: string }>('/api/v1/console/configs', 'PUT', { key, value }),
};

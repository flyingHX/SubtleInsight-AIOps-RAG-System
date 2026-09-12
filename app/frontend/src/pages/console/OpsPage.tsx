/** C10 审计日志 + 配置中心：审计链路检索、before/after 快照展示、配置项编辑。 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Save } from 'lucide-react';
import { toast } from 'sonner';
import { consoleApi, errDetail, type AuditLog, type ConfigItem } from '@/lib/console-api';
import { EmptyBlock, JsonPre, LoadingBlock, StateGate, fmtTime } from '@/components/console/shared';
import { usePermissions } from '@/components/console/ConsoleLayout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

const ACTION_LABELS: Record<string, string> = {
  feedback: '人工反馈',
  diagnosis_run: 'AI 诊断',
  kb_edit_submit: '知识库变更提交',
  kb_publish: '知识库发布',
  kb_rollback: '知识库回滚',
  merge_proposal_create: '合并提案创建',
  merge_apply: '合并执行',
  approval_approve: '审批通过',
  approval_reject: '审批拒绝',
  approval_withdraw: '审批撤回',
  rule_publish: '规则发布',
  rule_rollback: '规则回滚',
  unknown_promote_request: '未知模板晋升',
  unknown_discard: '未知模板废弃',
  config_update: '配置更新',
};

const TARGET_LABELS: Record<string, string> = {
  event: '告警事件',
  kb_case: '知识案例',
  kb_change_set: '知识变更集',
  kb_merge_proposal: '合并提案',
  approval_request: '审批单',
  rule_version: '规则版本',
  unknown_template: '未知模板',
  console_config: '控制台配置',
};

function AuditTab() {
  const [action, setAction] = useState('');
  const [actor, setActor] = useState('');
  const [targetType, setTargetType] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const query = useQuery({
    queryKey: ['audit-logs', action, actor, targetType],
    queryFn: () =>
      consoleApi.listAuditLogs({
        limit: 100,
        ...(action.trim() ? { action: action.trim() } : {}),
        ...(actor.trim() ? { actor: actor.trim() } : {}),
        ...(targetType.trim() ? { target_type: targetType.trim() } : {}),
      }),
  });

  const items = query.data?.items ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <Input className="h-9 w-44 text-xs" placeholder="操作（如 kb_publish）" value={action} onChange={(e) => setAction(e.target.value)} />
        <Input className="h-9 w-44 text-xs" placeholder="操作人（邮箱）" value={actor} onChange={(e) => setActor(e.target.value)} />
        <Input className="h-9 w-44 text-xs" placeholder="对象类型（如 kb_case）" value={targetType} onChange={(e) => setTargetType(e.target.value)} />
        <span className="text-xs text-muted-foreground">共 {query.data?.total ?? 0} 条审计记录</span>
      </div>

      <StateGate
        loading={query.isLoading}
        error={query.isError ? errDetail(query.error) : null}
        onRetry={() => query.refetch()}
        isEmpty={items.length === 0}
        empty="没有符合条件的审计记录"
        emptyHint="尝试清空筛选条件"
      >
        <Card>
          <CardContent className="p-0">
            <ul className="divide-y">
              {items.map((log: AuditLog) => {
                const open = expandedId === log.id;
                return (
                  <li key={log.id} className="px-4 py-3">
                    <button
                      className="flex w-full flex-wrap items-center gap-2 text-left text-xs"
                      onClick={() => setExpandedId(open ? null : log.id)}
                    >
                      <Badge variant="secondary">{ACTION_LABELS[log.action] ?? log.action}</Badge>
                      <span className="font-medium">{log.actor}</span>
                      <span className="text-muted-foreground">
                        {TARGET_LABELS[log.target_type] ?? log.target_type} · {log.target_id}
                      </span>
                      <span className="ml-auto text-muted-foreground">{fmtTime(log.created_at)}</span>
                    </button>
                    {open && (
                      <div className="mt-2.5 grid gap-2.5 lg:grid-cols-2">
                        <div>
                          <p className="mb-1 text-xs font-medium text-muted-foreground">变更前快照</p>
                          {log.before ? <JsonPre data={log.before} /> : <p className="text-xs text-muted-foreground">（无）</p>}
                        </div>
                        <div>
                          <p className="mb-1 text-xs font-medium text-muted-foreground">变更后快照</p>
                          {log.after ? <JsonPre data={log.after} /> : <p className="text-xs text-muted-foreground">（无）</p>}
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      </StateGate>
    </div>
  );
}

function ConfigTab() {
  const perms = usePermissions();
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const query = useQuery({ queryKey: ['configs'], queryFn: () => consoleApi.listConfigs() });

  const updateMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) => consoleApi.updateConfig(key, value),
    onSuccess: (res) => {
      toast.success(`配置 ${res.key} 已保存并写入审计`);
      queryClient.invalidateQueries({ queryKey: ['configs'] });
      queryClient.invalidateQueries({ queryKey: ['permissions'] });
    },
    onError: (e) => toast.error(`保存失败：${errDetail(e)}`),
  });

  if (query.isLoading) return <LoadingBlock rows={5} />;
  if (query.isError) {
    return (
      <EmptyBlock
        title="配置中心仅对系统管理员开放"
        hint={errDetail(query.error)}
      />
    );
  }

  const items = query.data?.items ?? [];
  const canManage = !!perms?.can_manage_config;

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        置信度阈值、重排权重、LLM 超时与审批模式等全局配置；修改后立即生效并写入审计日志。
        {!canManage && ` 当前角色（${perms?.role_label}）为只读。`}
      </p>
      <div className="grid items-start gap-3 lg:grid-cols-2">
        {items.map((cfg: ConfigItem) => {
          const draft = drafts[cfg.key] ?? cfg.value;
          const changed = draft !== cfg.value;
          return (
            <Card key={cfg.key}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <span className="font-mono">{cfg.key}</span>
                  {cfg.is_default && <Badge variant="outline">默认值</Badge>}
                  {cfg.key === 'approval_mode' && (
                    <Badge variant="secondary">{cfg.value === 'OFF' ? '免审直发' : cfg.value === 'SINGLE_REVIEW' ? '单级审批' : '多级审批'}</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <p className="text-xs text-muted-foreground">{cfg.description}</p>
                <div className="flex items-center gap-2">
                  <Input
                    className={cn('h-9 font-mono text-xs', changed && 'border-primary')}
                    value={draft}
                    disabled={!canManage || updateMutation.isPending}
                    onChange={(e) => setDrafts((s) => ({ ...s, [cfg.key]: e.target.value }))}
                  />
                  <Button
                    size="sm"
                    disabled={!canManage || !changed || updateMutation.isPending}
                    onClick={() => updateMutation.mutate({ key: cfg.key, value: draft })}
                  >
                    <Save className="mr-1.5 h-3.5 w-3.5" />
                    {updateMutation.isPending ? '保存中…' : '保存'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

export default function OpsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">审计与配置</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          全操作审计链路可追溯（含 before/after 快照），配置中心由系统管理员维护。
        </p>
      </div>
      <Tabs defaultValue="audit">
        <TabsList>
          <TabsTrigger value="audit">审计日志</TabsTrigger>
          <TabsTrigger value="config">配置中心</TabsTrigger>
        </TabsList>
        <TabsContent value="audit" className="mt-4">
          <AuditTab />
        </TabsContent>
        <TabsContent value="config" className="mt-4">
          <ConfigTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

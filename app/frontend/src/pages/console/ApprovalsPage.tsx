/** C8 审批中心：待我审批 / 我发起的 / 已处理，通过、拒绝、撤回与步骤时间线。 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, CircleDot, Clock, Undo2, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { consoleApi, errDetail, type ApprovalRequest } from '@/lib/console-api';
import { EmptyBlock, ErrorBlock, LoadingBlock, StatusBadge, fmtTime } from '@/components/console/shared';
import { useAuth } from '@/contexts/AuthContext';
import { usePermissions } from '@/components/console/ConsoleLayout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

const BIZ_TYPE_LABEL: Record<string, string> = {
  kb_edit: '知识库变更',
  kb_rollback: '知识库回滚',
  kb_merge: '知识合并',
  rule_publish: '规则发布',
  template_promote: '模板晋升',
};

const STEP_ACTION_META: Record<string, { label: string; icon: typeof CircleDot; className: string }> = {
  pending: { label: '待审批', icon: CircleDot, className: 'text-muted-foreground' },
  approved: { label: '已通过', icon: CheckCircle2, className: 'text-teal-600' },
  rejected: { label: '已拒绝', icon: XCircle, className: 'text-destructive' },
  withdrawn: { label: '已撤回', icon: Undo2, className: 'text-muted-foreground' },
  skipped: { label: '已跳过', icon: Undo2, className: 'text-muted-foreground' },
};

function StepTimeline({ request }: { request: ApprovalRequest }) {
  return (
    <ol className="mt-3 space-y-2.5 border-l pl-4">
      {request.steps.map((s) => {
        const meta = STEP_ACTION_META[s.action] ?? STEP_ACTION_META.pending;
        const Icon = meta.icon;
        return (
          <li key={s.id} className="relative">
            <Icon className={cn('absolute -left-[21.5px] h-4 w-4 bg-card', meta.className)} />
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-medium">步骤 {s.step_no} · {s.approver_role_label}</span>
              <Badge variant={s.action === 'approved' ? 'default' : s.action === 'rejected' ? 'destructive' : 'outline'}>
                {meta.label}
              </Badge>
              {s.approver && <span className="text-muted-foreground">{s.approver}</span>}
              {s.acted_at && <span className="text-muted-foreground">{fmtTime(s.acted_at, false)}</span>}
            </div>
            {s.comment && <p className="mt-1 text-xs text-muted-foreground">备注：{s.comment}</p>}
          </li>
        );
      })}
    </ol>
  );
}

function DecisionDialog({ request, action, onClose }: {
  request: ApprovalRequest;
  action: 'approve' | 'reject';
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [comment, setComment] = useState('');
  const mutation = useMutation({
    mutationFn: () => consoleApi.decideApproval(request.id, action, comment),
    onSuccess: (res) => {
      toast.success(action === 'approve' ? '已通过审批' : '已拒绝审批');
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['kb'] });
      onClose();
      void res;
    },
    onError: (e) => toast.error(`审批操作失败：${errDetail(e)}`),
  });

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{action === 'approve' ? '通过审批' : '拒绝审批'}</DialogTitle>
        <DialogDescription>
          {request.title}（#{request.id}）
          {action === 'approve' && ' 通过后系统将自动执行发布动作。'}
          {action === 'reject' && ' 拒绝后变更集将回退为草稿状态。'}
        </DialogDescription>
      </DialogHeader>
      <div>
        <Label className="mb-1 text-xs">审批意见{action === 'reject' ? '（建议填写）' : '（可选）'}</Label>
        <Textarea
          className="min-h-20 text-xs"
          placeholder="例如：方案可行，注意发布后观察告警趋势"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>取消</Button>
        <Button
          variant={action === 'approve' ? 'default' : 'destructive'}
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? '提交中…' : action === 'approve' ? '确认通过' : '确认拒绝'}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function ApprovalCard({ request, canDecide, myEmail }: { request: ApprovalRequest; canDecide: boolean; myEmail: string }) {
  const [decision, setDecision] = useState<'approve' | 'reject' | null>(null);
  const queryClient = useQueryClient();
  const withdrawMutation = useMutation({
    mutationFn: () => consoleApi.decideApproval(request.id, 'withdraw', ''),
    onSuccess: () => {
      toast.success('审批单已撤回');
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
    },
    onError: (e) => toast.error(`撤回失败：${errDetail(e)}`),
  });

  const isApplicant = request.applicant === myEmail;
  const canWithdraw = isApplicant && request.status === 'pending';
  const canAct = canDecide && request.status === 'pending' && !isApplicant;

  return (
    <Card>
      <CardContent className="space-y-2 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{BIZ_TYPE_LABEL[request.biz_type] ?? request.biz_type}</Badge>
          <span className="text-sm font-semibold">{request.title}</span>
          <StatusBadge status={request.status} className="ml-auto" />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>申请人：{request.applicant}（{request.applicant_role_label}）</span>
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {fmtTime(request.created_at)}
          </span>
          {request.risk_level && <span>风险等级：{request.risk_level}</span>}
          <span>
            进度：{request.current_step}/{request.total_steps} 步
          </span>
          <span>单号：#{request.id}</span>
        </div>
        {request.reason && <p className="text-xs text-muted-foreground">申请理由：{request.reason}</p>}

        <StepTimeline request={request} />

        {(canAct || canWithdraw) && (
          <div className="flex items-center gap-2 pt-1">
            {canAct && (
              <>
                <Button size="sm" onClick={() => setDecision('approve')}>
                  <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                  通过
                </Button>
                <Button size="sm" variant="destructive" onClick={() => setDecision('reject')}>
                  <XCircle className="mr-1.5 h-3.5 w-3.5" />
                  拒绝
                </Button>
              </>
            )}
            {canWithdraw && (
              <Button size="sm" variant="outline" onClick={() => withdrawMutation.mutate()} disabled={withdrawMutation.isPending}>
                <Undo2 className="mr-1.5 h-3.5 w-3.5" />
                {withdrawMutation.isPending ? '撤回中…' : '撤回申请'}
              </Button>
            )}
          </div>
        )}
        {isApplicant && request.status === 'pending' && (
          <p className="text-xs text-muted-foreground">你不能审批自己发起的申请。</p>
        )}

        {decision && (
          <Dialog open onOpenChange={(open) => !open && setDecision(null)}>
            <DecisionDialog request={request} action={decision} onClose={() => setDecision(null)} />
          </Dialog>
        )}
      </CardContent>
    </Card>
  );
}

function ApprovalListBox({ box, canDecide }: { box: 'pending' | 'created' | 'done'; canDecide: boolean }) {
  const { user } = useAuth();
  const myEmail = user?.email || user?.id || '';
  const query = useQuery({
    queryKey: ['approvals', box],
    queryFn: () => consoleApi.listApprovals(box),
  });

  if (query.isLoading) return <LoadingBlock rows={4} />;
  if (query.isError) {
    return <ErrorBlock message={`审批列表加载失败：${errDetail(query.error)}`} onRetry={() => query.refetch()} />;
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyBlock
        title={box === 'pending' ? '没有待你审批的请求' : box === 'created' ? '你还没有发起过审批' : '暂无已处理记录'}
        hint={box === 'pending' ? '新的知识库变更、合并或规则发布请求会出现在这里' : undefined}
      />
    );
  }
  return (
    <div className="space-y-3">
      {items.map((r) => (
        <ApprovalCard key={r.id} request={r} canDecide={canDecide} myEmail={myEmail} />
      ))}
    </div>
  );
}

export default function ApprovalsPage() {
  const perms = usePermissions();
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">审批中心</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          知识库变更、合并与规则发布的审批流；申请人不能审批自己的申请，通过后系统自动执行发布。
        </p>
      </div>
      <Tabs defaultValue="pending">
        <TabsList>
          <TabsTrigger value="pending">待我审批</TabsTrigger>
          <TabsTrigger value="created">我发起的</TabsTrigger>
          <TabsTrigger value="done">我已处理</TabsTrigger>
        </TabsList>
        <TabsContent value="pending" className="mt-4">
          <ApprovalListBox box="pending" canDecide={!!perms?.can_approve} />
        </TabsContent>
        <TabsContent value="created" className="mt-4">
          <ApprovalListBox box="created" canDecide={false} />
        </TabsContent>
        <TabsContent value="done" className="mt-4">
          <ApprovalListBox box="done" canDecide={false} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

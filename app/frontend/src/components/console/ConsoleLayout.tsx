/**
 * 控制台布局外壳：登录门控 + 权限上下文 + 侧边导航 + 顶栏。
 * 未登录时展示登录引导（client.auth.toLogin），不自动跳转，避免回调死循环。
 */
import { createContext, useContext, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { NavLink, Outlet } from 'react-router-dom';
import {
  Activity,
  BellRing,
  BookOpenText,
  ClipboardCheck,
  LayoutDashboard,
  LogOut,
  Menu,
  ScrollText,
  Settings2,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { consoleApi, errDetail, type Permissions } from '@/lib/console-api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { ErrorBlock } from './shared';
import { cn } from '@/lib/utils';

const PermissionsContext = createContext<Permissions | null>(null);

/** 当前用户权限（角色、can_* 能力位、审批模式）。 */
export const usePermissions = (): Permissions | null => useContext(PermissionsContext);

const NAV_ITEMS = [
  { to: '/', label: '运营总览', icon: LayoutDashboard },
  { to: '/events', label: '告警工作台', icon: BellRing },
  { to: '/kb', label: '知识库', icon: BookOpenText },
  { to: '/approvals', label: '审批中心', icon: ClipboardCheck },
  { to: '/rules', label: '规则管理', icon: ScrollText },
  { to: '/ops', label: '审计与配置', icon: Settings2 },
];

const APPROVAL_MODE_LABEL: Record<string, string> = {
  OFF: '免审直发',
  SINGLE_REVIEW: '单级审批',
  MULTI_LEVEL: '多级审批',
};

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-1">
      {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors',
              isActive
                ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
            )
          }
        >
          <Icon className="h-4 w-4" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

function LoginScreen() {
  const { login } = useAuth();
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-xl border bg-card p-8 text-center shadow-sm">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Activity className="h-6 w-6" />
        </div>
        <h1 className="text-xl font-semibold tracking-tight">AIOps 运营控制台</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          告警诊断、知识库治理与审批审计的一站式工作台。登录后按角色分配只读审计、值班运维、SRE、审批人与管理员权限。
        </p>
        <Button className="mt-6 w-full" onClick={login}>
          使用 Atoms 账号登录
        </Button>
      </div>
    </div>
  );
}

function FullSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
    </div>
  );
}

export default function ConsoleLayout() {
  const { status, user, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const permsQuery = useQuery({
    queryKey: ['permissions'],
    queryFn: () => consoleApi.getPermissions(),
    enabled: status === 'authenticated',
  });

  if (status === 'loading') return <FullSpinner />;
  if (status === 'anonymous') return <LoginScreen />;
  if (permsQuery.isLoading) return <FullSpinner />;
  if (permsQuery.isError || !permsQuery.data) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="w-full max-w-md">
          <ErrorBlock
            message={`权限信息加载失败：${errDetail(permsQuery.error)}`}
            onRetry={() => permsQuery.refetch()}
          />
        </div>
      </div>
    );
  }

  const perms = permsQuery.data;

  return (
    <PermissionsContext.Provider value={perms}>
      <div className="flex min-h-screen">
        {/* 桌面侧边栏 */}
        <aside className="hidden md:flex w-56 shrink-0 flex-col border-r bg-sidebar-background">
          <div className="flex items-center gap-2.5 px-4 py-4">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-semibold leading-tight">AIOps 控制台</p>
              <p className="text-xs text-muted-foreground">告警 · 知识库 · 审批</p>
            </div>
          </div>
          <div className="px-3">
            <NavLinks />
          </div>
          <div className="mt-auto px-4 py-4 text-xs text-muted-foreground">
            审批模式：
            <Badge variant="outline" className="ml-1">
              {APPROVAL_MODE_LABEL[perms.approval_mode] ?? perms.approval_mode}
            </Badge>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          {/* 顶栏 */}
          <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-card px-4 md:px-6">
            {/* 移动端菜单 */}
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="md:hidden">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-64 p-4">
                <SheetTitle className="mb-3 text-left">AIOps 控制台</SheetTitle>
                <NavLinks onNavigate={() => setMobileOpen(false)} />
              </SheetContent>
            </Sheet>

            <div className="ml-auto flex items-center gap-2.5">
              <Badge variant="secondary" className="hidden sm:inline-flex">
                {perms.role_label}
              </Badge>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
                    aria-label="用户菜单"
                  >
                    {(user?.name || user?.email || 'U').slice(0, 1).toUpperCase()}
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel className="font-normal">
                    <p className="truncate text-sm font-medium">{user?.name || '已登录用户'}</p>
                    <p className="truncate text-xs text-muted-foreground">{user?.email || user?.id}</p>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={logout} className="text-destructive focus:text-destructive">
                    <LogOut className="mr-2 h-4 w-4" />
                    退出登录
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </header>

          <main className="mx-auto w-full max-w-screen-xl flex-1 px-4 py-6 md:px-6">
            <Outlet />
          </main>
        </div>
      </div>
    </PermissionsContext.Provider>
  );
}

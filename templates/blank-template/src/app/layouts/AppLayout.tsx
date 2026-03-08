import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils';
import {
  Home,
  Menu,
  X,
  ChevronLeft,
} from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

const mainNavItems = [
  { name: 'Home', href: '/', icon: Home },
];

const systemNavItems = [];

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const location = useLocation();

  return (
    <div className="min-h-screen bg-background">
      {/* Mobile Header */}
      <header className="lg:hidden sticky top-0 z-50 flex items-center justify-between h-16 px-4 border-b border-border bg-background/95 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-2 -ml-2 rounded-lg hover:bg-muted transition-colors duration-150"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="w-8 h-8 rounded-xl bg-primary/10 flex items-center justify-center">
            <div className="w-4 h-4 rounded-md bg-primary" />
          </div>
        </div>
        <UserDropdown />
      </header>

      {/* Mobile Sidebar Overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm lg:hidden transition-opacity duration-200"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar - Desktop: Icon-first collapsible, Mobile: Full drawer */}
      <aside
        onMouseEnter={() => setSidebarExpanded(true)}
        onMouseLeave={() => setSidebarExpanded(false)}
        className={cn(
          'fixed inset-y-0 left-0 z-50 bg-sidebar border-r border-sidebar-border',
          'transition-all duration-250 ease-[cubic-bezier(0.2,0,0,1)]',
          // Mobile: full width drawer
          'lg:translate-x-0',
          sidebarOpen ? 'translate-x-0 w-64' : '-translate-x-full',
          // Desktop: collapsed/expanded
          sidebarExpanded ? 'lg:w-64' : 'lg:w-[72px]'
        )}
      >
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="flex items-center justify-between h-16 px-4 border-b border-sidebar-border">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center shrink-0 transition-transform duration-200 hover:scale-105">
                <div className="w-4 h-4 rounded-md bg-primary" />
              </div>
              <span className={cn(
                'font-semibold whitespace-nowrap overflow-hidden',
                'transition-all duration-200',
                sidebarExpanded ? 'opacity-100 w-auto sidebar-text-enter' : 'lg:opacity-0 lg:w-0'
              )}>
                DreamPilot
              </span>
            </div>
            <button
              onClick={() => setSidebarOpen(false)}
              className="p-2 -mr-2 rounded-lg hover:bg-sidebar-accent transition-colors duration-150 lg:hidden"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-3 overflow-y-auto">
            {/* Main Section */}
            <div className={cn(
              'nav-section-label transition-opacity duration-200',
              sidebarExpanded ? 'opacity-100' : 'lg:opacity-0'
            )}>
              Main
            </div>
            <div className="space-y-1">
              {mainNavItems.map((item) => {
                const isActive = location.pathname === item.href;
                return (
                  <Link
                    key={item.name}
                    to={item.href}
                    onClick={() => setSidebarOpen(false)}
                    className={cn(
                      'nav-item',
                      isActive ? 'nav-item-active' : 'nav-item-default',
                      !sidebarExpanded && 'lg:justify-center lg:px-0'
                    )}
                  >
                    <item.icon className="nav-icon h-5 w-5" />
                    <span className={cn(
                      'whitespace-nowrap overflow-hidden transition-all duration-200',
                      sidebarExpanded ? 'opacity-100 w-auto' : 'lg:opacity-0 lg:w-0 lg:hidden'
                    )}>
                      {item.name}
                    </span>
                  </Link>
                );
              })}
            </div>
          </nav>

          {/* User Section - Desktop */}
          <div className="p-3 border-t border-sidebar-border hidden lg:block">
            <UserDropdown full expanded={sidebarExpanded} />
          </div>

          {/* Expand indicator */}
          <div className={cn(
            'absolute top-1/2 -right-3 hidden lg:flex items-center justify-center',
            'w-6 h-6 rounded-full bg-sidebar border border-sidebar-border shadow-sm',
            'transition-all duration-200 cursor-pointer hover:bg-sidebar-accent',
            sidebarExpanded && 'rotate-180'
          )}>
            <ChevronLeft className="h-3 w-3 text-muted-foreground" />
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className={cn(
        'transition-all duration-250 ease-[cubic-bezier(0.2,0,0,1)]',
        sidebarExpanded ? 'lg:pl-64' : 'lg:pl-[72px]'
      )}>
        <div className="p-4 sm:p-6 lg:p-8 max-w-7xl page-enter">
          {children}
        </div>
      </main>
    </div>
  );
}

function UserDropdown({ full = false, expanded = true }: { full?: boolean; expanded?: boolean }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className={cn(
            'flex items-center gap-3 rounded-lg transition-all duration-200',
            'hover:bg-muted/60',
            full ? 'w-full p-2' : 'p-1',
            full && !expanded && 'lg:justify-center'
          )}
        >
          <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center text-primary text-sm font-semibold shrink-0 transition-transform duration-200 hover:scale-105">
            SC
          </div>
          {full && expanded && (
            <>
              <div className="flex-1 text-left min-w-0 sidebar-text-enter">
                <p className="text-sm font-medium truncate">Sarah Chen</p>
                <p className="text-xs text-muted-foreground">Admin</p>
              </div>
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56" sideOffset={8}>
        <div className="px-2 py-1.5">
          <p className="text-sm font-medium">Sarah Chen</p>
          <p className="text-xs text-muted-foreground">sarah.chen@company.com</p>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
// The top of every page: an optional breadcrumb trail, the title, a one-line description and
// actions on the right (wrapping under the title on narrow screens).
import Link from "next/link";
import type { ReactNode } from "react";

export type Crumb = { label: ReactNode; href?: string };

export function PageHeader({
  title,
  description,
  breadcrumb,
  trail,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  /** Parent pages, outermost first; the current page is the title, not a crumb. */
  breadcrumb?: Crumb[];
  /** After the crumbs on the breadcrumb line, e.g. a run's id, status and Replay link. */
  trail?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-2">
      {breadcrumb && breadcrumb.length > 0 && (
        <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-4">
          <ol className="flex flex-wrap items-center gap-1.5">
            {breadcrumb.map((crumb, i) => (
              <li key={i} className="flex items-center gap-1.5">
                {crumb.href ? (
                  <Link href={crumb.href} className="hover:text-foreground hover:underline">
                    {crumb.label}
                  </Link>
                ) : (
                  <span>{crumb.label}</span>
                )}
                <span aria-hidden className="text-ink-5">
                  /
                </span>
              </li>
            ))}
          </ol>
          {trail}
        </nav>
      )}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
          {description && <div className="text-sm text-ink-3 sm:text-base">{description}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-3">{actions}</div>}
      </div>
    </header>
  );
}

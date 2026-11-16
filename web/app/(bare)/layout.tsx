// The public pages' frame: no sidebar, tab bar or guide panel. The marketing page lives here,
// and /login, /invite/[token] and /reset/[token] go here too.
export default function BareLayout({ children }: LayoutProps<"/">) {
  return <main className="flex min-w-0 flex-1 flex-col">{children}</main>;
}

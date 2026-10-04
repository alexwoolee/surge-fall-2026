import { CheckCircle, WarningCircle, XCircle } from "@phosphor-icons/react/ssr";

export type OutcomeTone = "success" | "warning" | "danger";
const ICONS = { success: CheckCircle, warning: WarningCircle, danger: XCircle };

/** Card shell shared by every investigation outcome: icon, title, description, body, footer. */
export function Outcome({ tone, title, description, meta, children, footer, labelledBy }: {
  tone: OutcomeTone; title: React.ReactNode; description?: React.ReactNode; meta?: React.ReactNode;
  children?: React.ReactNode; footer?: React.ReactNode; labelledBy: string;
}) {
  const Icon = ICONS[tone];
  return <section className={`outcome outcome--${tone}`} aria-labelledby={labelledBy}>
    <header className="outcome-head">
      <Icon className="outcome-icon" size={20} weight="fill" aria-hidden="true" />
      <div className="outcome-heading">
        <h2 id={labelledBy} className="outcome-title">{title}</h2>
        {description && <p className="outcome-desc">{description}</p>}
      </div>
      {meta && <span className="outcome-meta">{meta}</span>}
    </header>
    {children && <div className="outcome-body">{children}</div>}
    {footer && <footer className="outcome-footer">{footer}</footer>}
  </section>;
}

/** Compact stat tiles for validated measurements. */
export function StatGrid({ items }: { items: { label: string; value: string }[] }) {
  return <dl className="stat-grid">{items.map((item) => <div className="stat" key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl>;
}

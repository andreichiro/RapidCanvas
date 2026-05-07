type ErrorBannerProps = {
  code?: string;
  details?: string[];
  message: string;
  status?: number;
  title?: string;
  tone?: "error" | "warning";
};

export default function ErrorBanner({ code, details = [], message, status, title, tone = "error" }: ErrorBannerProps) {
  const meta = [code, status ? `HTTP ${status}` : null].filter(Boolean);

  return (
    <div className={`notice notice-${tone}`} role={tone === "error" ? "alert" : "status"}>
      {title ? <strong>{title}</strong> : null}
      <span>{message}</span>
      {meta.length ? <span className="notice-meta">{meta.join(" - ")}</span> : null}
      {details.length ? (
        <ul className="notice-details">
          {details.map((detail, index) => (
            <li key={`${detail}-${index}`}>{detail}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

type ErrorBannerProps = {
  message: string;
  tone?: "error" | "warning";
};

export default function ErrorBanner({ message, tone = "error" }: ErrorBannerProps) {
  return (
    <div className={`notice notice-${tone}`} role={tone === "error" ? "alert" : "status"}>
      {message}
    </div>
  );
}

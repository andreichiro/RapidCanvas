import { type Trace } from "../api/client";

type TracePanelProps = {
  isOpen: boolean;
  onToggle: () => void;
  trace: Trace;
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function joinItems(items: string[]): string {
  return items.length ? items.join(", ") : "None";
}

export default function TracePanel({ isOpen, onToggle, trace }: TracePanelProps) {
  return (
    <section className="trace-section" aria-label="trace panel">
      <button aria-expanded={isOpen} className="trace-toggle" onClick={onToggle} type="button">
        {isOpen ? "Hide trace" : "Show trace"}
      </button>

      {isOpen ? (
        <div className="trace-panel">
          <dl>
            <div>
              <dt>Category</dt>
              <dd>{trace.category}</dd>
            </div>
            <div>
              <dt>Latency</dt>
              <dd>{trace.latency_ms} ms</dd>
            </div>
            <div>
              <dt>Trust</dt>
              <dd>{percent(trace.trust_score)}</dd>
            </div>
            <div>
              <dt>Fallback</dt>
              <dd>{trace.fallback_mode.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>Adapter</dt>
              <dd>{trace.adapter_mode.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>Queries</dt>
              <dd>{joinItems(trace.queries)}</dd>
            </div>
            <div>
              <dt>Warnings</dt>
              <dd>{joinItems(trace.warnings)}</dd>
            </div>
            <div>
              <dt>Flags</dt>
              <dd>{joinItems(trace.guardrail_flags)}</dd>
            </div>
            <div>
              <dt>Notes</dt>
              <dd>{joinItems(trace.adapter_notes)}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </section>
  );
}

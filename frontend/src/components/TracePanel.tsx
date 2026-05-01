import { type Trace } from "../api/client";

type TracePanelProps = {
  isOpen: boolean;
  onToggle: () => void;
  trace: Trace;
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function TraceList({ items }: { items: string[] }) {
  if (!items.length) {
    return <span>None</span>;
  }

  return (
    <ul className="trace-list">
      {items.map((item, index) => (
        <li key={`${item}-${index}`}>{item}</li>
      ))}
    </ul>
  );
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
              <dt>Trust score</dt>
              <dd>{percent(trace.trust_score)}</dd>
            </div>
            <div>
              <dt>Fallback mode</dt>
              <dd>{trace.fallback_mode.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>Adapter mode</dt>
              <dd>{trace.adapter_mode.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>Queries</dt>
              <dd>
                <TraceList items={trace.queries} />
              </dd>
            </div>
            <div>
              <dt>Warnings</dt>
              <dd>
                <TraceList items={trace.warnings} />
              </dd>
            </div>
            <div>
              <dt>Guardrail flags</dt>
              <dd>
                <TraceList items={trace.guardrail_flags} />
              </dd>
            </div>
            <div>
              <dt>Adapter notes</dt>
              <dd>
                <TraceList items={trace.adapter_notes} />
              </dd>
            </div>
          </dl>
        </div>
      ) : null}
    </section>
  );
}

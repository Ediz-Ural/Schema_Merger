export type Step = "upload" | "review" | "done";

const STEPS: { id: Step; label: string }[] = [
  { id: "upload", label: "Yükle ve analiz et" },
  { id: "review", label: "Planı onayla" },
  { id: "done", label: "Birleştir ve indir" },
];

/** Where the user stands in the two-phase flow -- the flow made visible. */
export function StepBar({ current }: { current: Step }) {
  const index = STEPS.findIndex((step) => step.id === current);
  return (
    <ol className="steps" aria-label="Akış">
      {STEPS.map((step, position) => {
        const state = position < index ? "done" : position === index ? "current" : "todo";
        return (
          <li key={step.id} className={`steps__item steps__item--${state}`} aria-current={state === "current"}>
            <span className="steps__index" aria-hidden="true">
              {position < index ? "✓" : position + 1}
            </span>
            <span className="steps__text">
              <strong>{step.label}</strong>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export default StepBar;

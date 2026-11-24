// Server component: who it is for and what it does not claim (static copy, no hydration cost).
import { BENEFITS, IMPACT, LIMITS } from "@/lib/site-copy";

export function Aftermath() {
  return (
    <section className="as-after" aria-labelledby="after-h">
      <h2 id="after-h" className="as-after-title">
        Who it is for, and what it does not claim
      </h2>
      <div className="as-cols">
        <div>
          <h3>Who benefits</h3>
          <ul className="rows">
            {BENEFITS.map((b) => (
              <li key={b.who}>
                <strong>{b.who}</strong>
                <span>{b.body}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Expected impact</h3>
          <ul className="rows rows-one">
            {IMPACT.map((i) => (
              <li key={i}>
                <span>{i}</span>
              </li>
            ))}
          </ul>
        </div>
        <div id="limits">
          <h3>What ActionProof does not claim</h3>
          <ul className="rows">
            {LIMITS.map((l) => (
              <li key={l.head}>
                <strong>{l.head}</strong>
                <span>{l.body}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

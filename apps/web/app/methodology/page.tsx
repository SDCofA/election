import Link from "next/link";

const gates = [
  "At least eight strict forecast-origin folds across three held-out elections and twenty years of history",
  "Immutable revision hashes for fundamentals, every poll snapshot, and results",
  "All inputs must have release timestamps at or before each forecast cutoff",
  "Election-clustered paired-bootstrap Brier superiority at 90% confidence",
  "Vote-share RMSE no more than 5% worse than best baseline",
  "Empirical 90% interval coverage of at least 80%"
];
export default function MethodologyPage() {
  return (
    <main className="method-page">
      <Link className="method-back" href="/">← SDCOFA ELECTION DESK</Link>
      <header>
        <span>MODEL GOVERNANCE / VERSION 0.3</span>
        <h1>Forecast methodology</h1>
        <p>Evidence gates choose the public model. No challenger is promoted because it looks more sophisticated.</p>
      </header>

      <section>
        <h2>Current publication state</h2>
        <p>The public forecast uses a widened baseline ensemble. Gaussian Monte Carlo and Markov-momentum models each run 1,000,000 deterministic scenarios as challengers, and every production backtest model-fold uses 1,000,000 predictive draws for winner probabilities and 90% intervals. Markov leads the U.S. short-horizon historical Brier score, while Gaussian has better RMSE and interval coverage; neither is promoted because 2–14-day evidence cannot validate the current early-cycle horizon. Forecasts without source-vintage feature snapshots are forced to grade D and list zero model-input sources.</p>
      </section>

      <section className="method-grid">
        <article>
          <span>CHALLENGER A</span>
          <h2>Gaussian Monte Carlo</h2>
          <p>Samples exchangeable zero-sum multi-contestant shocks, economic and security shocks, turnout uncertainty, house effects, and election-system translation. Contestant order never assigns a favorable or unfavorable sign.</p>
        </article>
        <article>
          <span>CHALLENGER B</span>
          <h2>Markov momentum</h2>
          <p>Uses a three-state campaign-movement chain with persistent down, neutral, and up states. Transition probabilities and movement size are estimated only from training elections; remaining campaign steps follow the forecast horizon.</p>
        </article>
      </section>

      <section>
        <h2>Promotion gates</h2>
        <ol>{gates.map((gate) => <li key={gate}>{gate}</li>)}</ol>
        <p>Challengers are compared with polls-only, fundamentals-only, and previous-election baselines. Failure of any gate retains the validated baseline.</p>
      </section>

      <section>
        <h2>System engines and limits</h2>
        <p>Engines cover presidential runoff transfers, FPTP seat elasticity, thresholded proportional and mixed-member allocation, and electoral-college translation. District or state maps remain suppressed until validated boundary-level inputs exist. Early structural forecasts carry low quality grades and wide intervals.</p>
      </section>

      <section>
        <h2>Driver sensitivity</h2>
        <p>Each matrix row varies one standardized driver contribution from −1 to +1 while every other model input remains fixed. Values are structural incumbent vote-share shifts, not causal estimates or win probabilities. The simulation&apos;s ±2.5-point cap is applied and visibly flagged.</p>
      </section>

      <section>
        <h2>Data integrity</h2>
        <p>Raw responses are content-addressed and immutable. Every observation preserves observed, released, available, and retrieved timestamps. Model cutoffs enforce all four clocks. Adapters reject unapproved reuse terms before network access and retain last-known-good canonical records when parser confidence falls.</p>
        <div className="method-links">
          <a href="https://www.v-dem.net/data/the-v-dem-dataset/">V-Dem eligibility</a>
          <a href="https://api.worldbank.org/v2/">World Bank indicators</a>
          <Link href="/docs">REST / OpenAPI</Link>
        </div>
      </section>

      <section>
        <h2>Global coverage states</h2>
        <p>Every catalog jurisdiction has a public election record. Unknown dates are shown as TBD with unresolved mechanics and no probability. Link-only authority references are never scraped or treated as licensed data; dated calendar and forecast status require separate validation gates.</p>
        <div className="method-links"><Link href="/calendar">Global election directory</Link></div>
      </section>
    </main>
  );
}

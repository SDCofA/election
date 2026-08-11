import Link from "next/link";

import { publicAsset } from "@/lib/public-data";

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
        <span>MODEL GOVERNANCE / VERSION 0.5</span>
        <h1>Forecast methodology</h1>
        <p>Evidence gates choose the public model. No challenger is promoted because it looks more sophisticated.</p>
      </header>

      <section>
        <h2>Current publication state</h2>
        <p>The public forecast uses a widened baseline ensemble. Version 0.5 scores that public baseline alongside Gaussian Monte Carlo, Markov momentum, polls-only, fundamentals-only, and previous-election benchmarks. Every production model-fold uses 1,000,000 predictive draws for winner probabilities and 90% intervals. Training origins must fall within 10% of the held-out horizon, bounded to a two-to-thirty-day tolerance. Production horizons must be near an evaluated fold—not merely between the shortest and longest tests. No challenger is promoted because 2–14-day U.S. evidence cannot validate the current early-cycle horizon. The 12 U.S. folds use a pinned retrospective poll compilation, not forecast-origin archived vintages, so they also fail the vintage-proof gate. Forecasts without source-vintage feature snapshots are forced to grade D and list zero model-input sources.</p>
        <p>Türkiye now has three archive-verified forecast-origin folds, each using 1,000,000 draws after training on 2014 and 2018. All three hold out the same 2023 election, cover only 2–14-day horizons, and span nine years, so they remain diagnostic and cannot validate or promote a model. The current headline is a separate mixture of three May 2026 matchups—Erdoğan against İmamoğlu, Yavaş, and Özel. Equal matchup weights are structural placeholders, not nomination probabilities.</p>
        <p>Australia has nine archive-verified folds across three held-out elections. Markov momentum leads narrowly in the 7–28-day tests, but the 2010–2025 history is too short and the current election is far outside the tested horizon. It is therefore not promoted.</p>
      </section>

      <section>
        <h2>Research doctrine: context without guesswork</h2>
        <p>Version 0.5 disables every hand-written economy, security, conflict, crime, and incumbency coefficient. Context rows remain reporting signals, but contribute exactly zero to published probabilities. A driver activates only after its value was observable at each historical cutoff, its direction is fitted from training elections, and the complete country-specific model beats simpler alternatives on unseen elections.</p>
        <p>There is no universal “war moves voters right” rule. Research finds conditional, time-varying, and sometimes null security effects. The intended model uses issue salience together with local party ownership, incumbent responsibility, shock timing and decay—and estimates their interactions separately by political system. Economic variables are relative to peer-country performance and moderated by clarity of government responsibility.</p>
        <div className="method-links">
          <a href="https://www.cambridge.org/core/journals/political-analysis/article/forecasting-elections-in-multiparty-systems-a-bayesian-approach-combining-polls-and-fundamentals/CA929544F672A09A0E34C5529EBFA482">Bayesian polls + fundamentals</a>
          <a href="https://www.michaelperess.com/research/Benchmarking.pdf">Cross-border economic benchmarking</a>
          <a href="https://www.sciencedirect.com/science/article/pii/S0261379408000024">Issue salience × ownership</a>
          <a href="https://www.cambridge.org/core/journals/british-journal-of-political-science/article/doubleedged-bullets-the-conditional-effect-of-terrorism-on-vote-for-the-incumbent/65DD603740265C5391341B7BB7B7C43F">Time-dependent security effects</a>
          <a href="https://www.cambridge.org/core/journals/perspectives-on-politics/article/jihadist-terrorist-attacks-and-farright-party-preferences-an-unexpected-event-during-survey-design-in-four-european-countries/EBC6F9354B018A82EE87661DB690D3A3">Security null-effects test</a>
        </div>
      </section>

      <section>
        <h2>Time and candidate uncertainty</h2>
        <p>Model volatility is calibrated at a 90-day reference horizon. Version 0.5 applies a transparent time multiplier: (days to election ÷ 90)<sup>0.18</sup>, bounded from 0.75× to 1.60×. Long-range forecasts therefore widen automatically instead of behaving like twelve-week calls. For unsettled ballots, one million draws sample a candidate scenario first and electoral uncertainty second; the public headline is the resulting mixture, while every conditional distribution remains visible.</p>
        <p>One million runs reduce numerical simulation noise. They do not erase polling error, candidate uncertainty, model misspecification, or missing historical validation; those remain visible through intervals, scenario splits, quality grades, fold counts, and vintage-proof status.</p>
        <div className="method-links">
          <a href="https://www.cambridge.org/core/journals/political-analysis/article/forecasting-elections-in-multiparty-systems-a-bayesian-approach-combining-polls-and-fundamentals/CA929544F672A09A0E34C5529EBFA482">Polls + fundamentals research</a>
          <a href="https://arxiv.org/abs/2206.14570">Hidden-state polling error research</a>
        </div>
      </section>

      <section>
        <h2>Forecast availability policy</h2>
        <p>Official nominations, final electoral mechanics, and machine-reuse permission affect certainty. A one-million-run forecast publishes only when a defensible electoral probability target exists. When a genuine ballot is unsettled, the model uses explicitly labeled candidate, party, alliance, or governing-versus-opposition scenarios. Where there is no national popular election—or evidence cannot support a probability—the country remains a sourced calendar-only record. Reference-only sources are linked but never ingested.</p>
        <p>These proxy forecasts are grade D. They are not presented as validated candidate polls, and they cannot promote a challenger model. Names and mechanics replace proxies as reproducible source-vintage evidence arrives.</p>
      </section>

      <section className="method-grid">
        <article>
          <span>CHALLENGER A</span>
          <h2>Gaussian Monte Carlo</h2>
          <p>Samples exchangeable zero-sum multi-contestant shocks, turnout uncertainty, house effects, and election-system translation. Unvalidated contextual drivers have no directional effect. Contestant order never assigns a favorable or unfavorable sign.</p>
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
        <p>Engines cover presidential runoff transfers, FPTP seat elasticity, thresholded proportional and mixed-member allocation, electoral-college translation, institutional regional paths, and unresolved national-control scenarios. District or state maps remain suppressed until validated boundary-level inputs exist. Early structural forecasts carry low quality grades and wide intervals.</p>
      </section>

      <section>
        <h2>Driver sensitivity</h2>
        <p>Sensitivity matrices are suppressed unless coefficients come from a promoted, source-vintage model. Qualitative context can explain what analysts are monitoring; it cannot silently alter a probability.</p>
      </section>

      <section>
        <h2>Data integrity</h2>
        <p>Raw responses are content-addressed and immutable. Every observation preserves observed, released, available, and retrieved timestamps. Model cutoffs enforce all four clocks. Adapters reject unapproved reuse terms before network access and retain last-known-good canonical records when parser confidence falls.</p>
        <div className="method-links">
          <a href="https://www.v-dem.net/data/the-v-dem-dataset/">V-Dem eligibility</a>
          <a href="https://api.worldbank.org/v2/">World Bank indicators</a>
          <a href="https://github.com/SDCofA/election/blob/master/services/api/app/backtests/tr-presidential-2014-2023-v1.json">Türkiye backtest dataset</a>
          <a href={publicAsset("/data/openapi-v1.json")}>REST / OpenAPI</a>
        </div>
      </section>

      <section>
        <h2>G20 coverage states</h2>
        <p>Public scope is limited to the 19 sovereign G20 countries. The European Union and African Union are excluded. All 19 now have sourced national election-status records. Sixteen carry forecasts; China and Saudi Arabia remain calendar-only because no national popular executive or legislative-control ballot exists, while Russia remains calendar-only until an official timetable, candidate field, and approved source-vintage evidence support a probability.</p>
        <div className="method-links"><Link href="/calendar">G20 election directory</Link></div>
      </section>
    </main>
  );
}

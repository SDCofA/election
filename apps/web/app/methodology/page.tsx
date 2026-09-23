import Image from "next/image";
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
      <div className="method-brand-row">
        <Link className="method-brand" href="/" aria-label="Elexion home">
          <Image alt="Elexion election intelligence" height={64} src={publicAsset("/brand/elexion-logo.svg")} width={320} priority />
        </Link>
        <Link className="method-back" href="/">← FORECAST DESK</Link>
      </div>
      <header>
        <span>MODEL GOVERNANCE / VERSION 0.6.1</span>
        <h1>Forecast methodology</h1>
        <p>Evidence gates choose the public model. No challenger is promoted because it looks more sophisticated.</p>
      </header>

      <section>
        <h2>Current publication state</h2>
        <p>No numerical election forecast is currently public. Version 0.6 compares a baseline ensemble with Gaussian Monte Carlo, Markov momentum, polls-only, fundamentals-only, and previous-election benchmarks as research. Its one-million-draw simulations reduce numerical noise but cannot replace missing source-vintage inputs or election-specific validation. The U.S. folds use a retrospective poll compilation rather than forecast-origin archived vintages and cover only 2–14-day horizons. All current structural simulations are grade D, have no traceable model-input revisions, and are withheld from the public dashboard and forecast API.</p>
        <p>Türkiye has three archive-verified diagnostic folds trained on 2014 and 2018 and held out on the same 2023 election. They cover only 2–14-day horizons across nine years, so they cannot validate a current forecast. Research matchup scenarios are withheld; their equal weights were structural placeholders, not nomination probabilities.</p>
        <p>Australia has 14 archive-verified folds across five held-out elections and 21 years. Markov momentum has the best election-clustered Brier score in the 7–28-day tests (0.166 versus 0.223 for Gaussian Monte Carlo and 0.279 for the fitted baseline). The next election remains far outside the tested horizon, so no current long-range probability is published.</p>
      </section>

      <section>
        <h2>Research doctrine: context without guesswork</h2>
        <p>Version 0.6 disables hand-written economy, security, conflict, crime, and incumbency coefficients. Context rows remain reporting signals and do not create a public probability. A driver can activate only after its value is observable at each historical cutoff, its direction is fitted from training elections, and the country-specific model beats simpler alternatives on unseen elections.</p>
        <p>The polls-versus-fundamentals weight is no longer fixed at 72/28. Every historical fold fits a constrained zero-to-one weight using prior elections only, with each election receiving equal weight regardless of archive density. The held-out election cannot influence that coefficient. A current forecast may use the fitted blend only when its country report passes every reliability and horizon gate; otherwise an available poll aggregate remains polls-only.</p>
        <p>There is no universal “war moves voters right” rule. Research finds conditional, time-varying, and sometimes opposite security effects. The intended model first gates on current issue salience, then uses party ownership, incumbent responsibility, shock timing, geography and decay. A security coefficient stays off when current salience is low or country-specific walk-forward validation is insufficient; it is never activated merely because a conflict exists.</p>
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
        <p>The research simulation uses a 90-day reference horizon and a transparent time multiplier: (days to election ÷ 90)<sup>0.18</sup>, bounded from 0.75× to 1.60×. For unsettled ballots, draws sample a candidate scenario and then electoral uncertainty. These simulated distributions are withheld until traceable current inputs and validation support publication.</p>
        <p>One million runs reduce numerical simulation noise. They do not erase polling error, candidate uncertainty, model misspecification, or missing historical validation.</p>
        <div className="method-links">
          <a href="https://www.cambridge.org/core/journals/political-analysis/article/forecasting-elections-in-multiparty-systems-a-bayesian-approach-combining-polls-and-fundamentals/CA929544F672A09A0E34C5529EBFA482">Polls + fundamentals research</a>
          <a href="https://arxiv.org/abs/2206.14570">Hidden-state polling error research</a>
        </div>
      </section>

      <section>
        <h2>Forecast availability policy</h2>
        <p>Official nominations, final electoral mechanics, and machine-reuse permission affect certainty. A one-million-run forecast publishes only when a defensible electoral probability target exists. When a genuine ballot is unsettled, the model uses explicitly labeled candidate, party, alliance, or governing-versus-opposition scenarios. Where there is no national popular election—or evidence cannot support a probability—the country remains a sourced calendar-only record. Reference-only sources are linked but never ingested.</p>
        <p>These proxy simulations are grade D. The public dashboard withholds their numerical win probabilities. Reproducible research artifacts remain labeled grade D and do not represent a current election call. Names and mechanics replace proxies as source-vintage evidence arrives.</p>
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
        <p>Challengers are compared with a training-fitted poll/fundamentals ensemble, polls-only, fundamentals-only, and previous-election baselines. Failure of a publication gate withholds the numerical forecast.</p>
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
          <a href="https://github.com/SDCofA/election/blob/master/services/api/app/backtests/au-federal-tpp-2004-2025-v2.json">Australia backtest dataset</a>
          <a href={publicAsset("/visual-assets.json")}>Flags, portraits &amp; logos ledger</a>
          <a href={publicAsset("/data/openapi-v1.json")}>REST / OpenAPI</a>
        </div>
      </section>

      <section>
        <h2>G20 coverage states</h2>
        <p>Public scope is limited to the 19 sovereign G20 countries. The European Union and African Union are excluded. All 19 have sourced national election-status records. No country currently has a public numerical forecast. Sixteen structural research simulations are grade D and withheld; China, Saudi Arabia, and Russia were already calendar-only.</p>
        <div className="method-links"><Link href="/calendar">G20 election directory</Link></div>
      </section>
    </main>
  );
}

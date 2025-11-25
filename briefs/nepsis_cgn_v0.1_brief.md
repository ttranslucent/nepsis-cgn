NepsisCGN v0.2-pre update (work-in-progress)

- Architecture spine preserved: triage → projection → validation with ZeroBack repair loop and ruin gate.
- Providers: added OpenAIProvider (env-only OPENAI_API_KEY) plus model factory (simulated/gpt*).
- Manifolds:
  - WordGameManifold: multiset red-channel with repair deltas.
  - UTF8HiddenManifold: enforces hidden U+200B marker after target phrase.
  - SeedManifold (Voronoi-based): neutral adversarial reasoning demo with forbidden-token ruin seed and utility seeds; drift detection based on region flips/ruin-distance oscillation; blue score uses Voronoi margin.
- Geometry: added additive-weighted NepsisVoronoi engine for seed-based partitioning.
- Meta: DevianceMonitor adjusts tau_R when near-miss history is high.
- CLI: supports --mode word_game|utf8|seed and --model selection; routes through provider factory.
- Tests: added coverage for word-game multiset, UTF-8 hidden marker, seed manifold, and deviance monitor (pytest passing).

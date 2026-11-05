# Roadmap after Phase 2

Implemented in Phase 2: shared budgets, recovery recipes and lineage, independent invoices,
explicit write service contracts, offline native-adapter tests, fixed-scale dashboard, and
versioned live smoke/pilot protocols with sourced cost previews.

The public release is complete as an offline lab. Real-provider tests are intentionally not
being run; none of the ideas below are requirements for using or publishing the project.

1. Optionally validate a real-provider integration and run a separately designed live study.
   Existing smoke/pilot configurations are unexecuted examples, not model robustness evidence.
2. Add larger paired studies with uncertainty methods that account for scenario clustering.
3. Add authenticated source provenance and experiments on correlated corruption.
4. Add optional provider-specific tokenizers, cache-aware pricing breakdowns and stronger redaction.
5. Add cancellation-resistant handler process isolation and optional OpenTelemetry export.

Keep synthetic execution and independent state assertions as defaults. Production integration,
distributed orchestration and cloud deployment remain outside this project's scope.

# Roadmap

1. Add an independent invoice provenance source to study recovery from schema-valid source corruption.
2. Add deliberately unsafe retry as an explicitly labeled experimental baseline, separate from
   supported safe policies, to quantify duplicate side effects across experiments. The current
   boundary tests already demonstrate the non-deduplicating service's risk.
3. Add scenario-level confidence intervals and paired policy comparisons for larger live samples.
4. Add configurable pricing only with explicit source/date, plus stronger credential/PII redaction.
5. Add fault plugins, cancellation-resistant tool process isolation, and optional OpenTelemetry export.

Keep local synthetic execution and independent state assertions as the default. Production
integration, distributed orchestration and cloud deployment are outside the present scope.

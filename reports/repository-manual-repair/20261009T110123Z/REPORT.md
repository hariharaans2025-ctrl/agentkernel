# Queue barrier repair

Origin: human-authored repair, not a model success. Model calls: 0. Tokens: 0.

Both threads now rendezvous before holding either shared mutex. Both acquire queue then stats and release in reverse order. The barrier, workload, semantic oracle, test counts and timeouts are retained.

- Overall verified: True
- Stress: 100/100
- Original tests: True
- Semantics: True
- Required TSan: True (3 configured runs; raw evidence in campaign-2.json)
- Infrastructure failures: 0
- Protected files unchanged: 500

The repaired project is exported in repaired-project/. Only src/queue.c differs from the original. Original fixtures and all earlier evidence remain unchanged. This result covers the configured synthetic workload, not proof of correctness for arbitrary applications.

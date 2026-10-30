# Frozen cloud routing comparison

Eight existing synthetic test designs. Prospective matched comparison, not proof of pretraining novelty or production superiority.

| Route | Completed | Verified | Calls | Ultra calls | Tokens | USD | Median e2e (s) | False-fix candidates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| super_only | 8 | 0 | 8 | 0 | 12496 | 0.0043578 | 18.3816547000024 | 4 |
| ultra_only | 8 | 6 | 8 | 8 | 13055 | 0.015955 | 40.781171000009635 | 2 |
| fast | 8 | 6 | 16 | 8 | 25743 | 0.020602 | 43.553339799982496 | 4 |

Unknowns are separate from failures. Failed candidates consume tokens/cost. Adaptive can cost more than Ultra-only when Super fails. Do not infer statistical superiority from this suite.

Complete: True. No post-result prompt, fixture, cap or routing changes. Full raw evidence is under each case/arm.

## Independent outcome audit

Adaptive stopped at Super on 0 cases; Ultra recovered 6; 2 remained unresolved. Ultra calls after a verified Super: 0.

Adaptive was cheaper than Ultra-only on 0 cases and more expensive on 8. Compare the verified outcomes alongside these costs.

The verifier rejected 0 candidate attempts that passed stress and semantics but failed TSan. These are not accepted repairs.

This is a single-pass synthetic-suite comparison. No confidence claim or production generalization follows from these counts.

## Claims supported by this run

- On this suite adaptive verified 6/8 versus Super-only 0/8.
- Adaptive cost more than Ultra-only in this run; a cost-saving claim is unsupported.

# Generate case candidates

Use this capability when the user wants new case candidates. It can be composed with inspect_reuse for gaps, but no query/reuse sequence is mandatory. Exact counts and source provenance are constraints, not suggestions.

Reuse the existing generation brief and its exact human review boundary. If no approved current brief exists, prepare_generation computes the brief; it does not self-approve it. A real user confirmation schedules the existing durable generation worker. Do not manufacture an approval, invoke an alternative writer, or regenerate a still-running job. Tool/run observations determine whether work is computing, awaiting brief review, or awaiting candidate review.

Only the requested scope and count may be generated. Retain source/selection versions, unknowns, quality warnings and incomplete candidates. Candidate generation is not formal adoption. Only a later explicit user action may adopt exact reviewed candidates. Do not claim completion from loading this skill or from an old run's receipt.

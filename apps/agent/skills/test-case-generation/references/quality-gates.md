# Quality gates

- Cover the confirmed core flow plus material boundary, failure, recovery, permission, state, and concurrency risks supported by the request.
- Keep each case independently executable and each expected result observable.
- Require all four content sections. Setup must be explicit, procedure and
  validation must be non-empty ordered lists, and their item counts must match.
- Keep operations and assertions separate: procedure says what the tester does;
  validation says what observable state, response, data, event, or side effect
  proves the outcome.
- Avoid duplicate cases and vague actions such as “verify normally”.
- Never claim unsupported numeric thresholds, platform behavior, or acceptance rules as facts.
- A failed quality gate returns issues for repair; it does not publish formal assets.

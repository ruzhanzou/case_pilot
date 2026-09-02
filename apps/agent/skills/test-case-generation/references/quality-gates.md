# Quality gates

- Cover the confirmed core flow plus material boundary, failure, recovery, permission, state, and concurrency risks supported by the request.
- Keep each case independently executable and each expected result observable.
- Avoid duplicate cases and vague actions such as “verify normally”.
- Never claim unsupported numeric thresholds, platform behavior, or acceptance rules as facts.
- A failed quality gate returns issues for repair; it does not publish formal assets.

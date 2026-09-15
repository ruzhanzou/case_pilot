# Output contract

Generation proceeds through requirement analysis, feature points, test points, test cases, then quality validation.

- Every feature point references a requirement.
- Every test point references at least one feature point.
- Every test case references at least one test point.
- Every case has a stable candidate id plus the required content fields `title`,
  `test_setup`, `test_procedure`, and `test_validation`. Module, priority, type,
  tags, test-point references, and evidence references remain traceability metadata.
- `title` states one test objective and expected scenario; it does not contain
  execution steps.
- `test_setup` lists the environment, state, identity, permission, and test-data
  prerequisites. Use an explicit "无特殊前置条件" item when no setup is needed.
- `test_procedure` is an ordered list of independently executable operations.
  Each item contains an action only and does not mix in an expected result.
- `test_validation` is an ordered list of observable assertions. It has the same
  item count and index correspondence as `test_procedure`.
- Runtime persistence maps `test_setup` to `preconditions`, and pairs
  `test_procedure[n]` with `test_validation[n]` as the stored step. This is a
  compatibility adapter, not a different generation contract.
- Preserve evidence references with source label and locator when evidence is used.

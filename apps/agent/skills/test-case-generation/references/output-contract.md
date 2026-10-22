# Output contract

Complete only the current stage using its supplied JSON Schema.

- Requirement, feature, test point and candidate identities stay traceable. Only emit identity fields included in the current schema; the server assigns the others.
- For `case_batch_v2`, return `test_cases` containing exactly the requested slots. Each entry contains only `slot`, `title`, `preconditions`, and `steps`.
- `title` states one objective and scenario, without execution steps.
- `preconditions` describe the required state, identity and test data. Use an explicit no-special-setup item when appropriate.
- Each `steps` entry contains `action` and `expected`. Actions are executable operations; expectations are observable assertions. One may be empty when operations and checkpoints do not correspond one-to-one, but every case must contain both an operation and an assertion.
- Do not emit `test_setup`, `test_procedure`, or `test_validation` unless the current schema explicitly requests those fields.
- In compact generation the server derives module, priority, test-point links, source identity and provenance from the reviewed plan. Do not fabricate or duplicate them in model output.
- In other stages preserve source identifiers exactly as supplied, within the current schema.

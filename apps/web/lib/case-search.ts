import type { CaseCollectionDto, TestCaseDto } from "@/lib/casepilot-api";

export function matchesCollectionSearch(
  collection: CaseCollectionDto,
  query: string,
) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return true;

  const target = collection.test_target;
  const targetValues = target
    ? [
        target.source_system,
        target.target_type,
        String(target.target_id),
        target.target_key,
        target.title,
        ...target.linked_fr_ids.map(String),
        ...target.linked_qpm_ids.map(String),
      ]
    : [];
  const creatorValues = collection.creator
    ? [
        collection.creator.id,
        collection.creator.display_name,
        collection.creator.email,
      ]
    : [];
  const document = [
    collection.name,
    collection.description,
    ...creatorValues,
    ...targetValues,
  ]
    .join(" ")
    .toLocaleLowerCase();

  return terms.every((term) => document.includes(term));
}

export function matchesCaseSearch(testCase: TestCaseDto, query: string) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return true;

  const targetValues = (testCase.test_targets ?? []).flatMap((target) => [
    target.source_system,
    target.target_type,
    String(target.target_id),
    target.target_key,
    target.title,
    ...target.linked_fr_ids.map(String),
    ...target.linked_qpm_ids.map(String),
  ]);
  const creatorValues = testCase.creator
    ? [
        testCase.creator.id,
        testCase.creator.display_name,
        testCase.creator.email,
      ]
    : [];
  const document = [
    testCase.case_key,
    testCase.title,
    testCase.module,
    testCase.case_type,
    testCase.priority,
    testCase.source,
    ...testCase.tags,
    ...creatorValues,
    ...targetValues,
  ]
    .join(" ")
    .toLocaleLowerCase();

  return terms.every((term) => document.includes(term));
}

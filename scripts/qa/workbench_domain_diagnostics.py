"""Audited constant-only domain diagnostics for local QA. Never emit exception text.

The static maps are deliberately not populated by runtime exception messages or
source introspection. Adding a domain contract requires an explicit code review.
"""
from contextlib import suppress
from uuid import UUID

DOMAIN_CODES = {
    "planning_boundary_source_invalid": "planning_boundary_source_invalid",
    "planning_boundary_literal_invalid": "planning_boundary_literal_invalid",
    "planning_boundary_threshold_invalid": "planning_boundary_threshold_invalid",
    "planning_boundary_unit_invalid": "planning_boundary_unit_invalid",
    "planning_boundary_axis_invalid": "planning_boundary_axis_invalid",
    "planning_boundary_time_origin_invalid": "planning_boundary_time_origin_invalid",
    "planning_boundary_sampling_invalid": "planning_boundary_sampling_invalid",
    "planning_boundary_sample_link_invalid": "planning_boundary_sample_link_invalid",
    "planning_boundary_coordinate_invalid": "planning_boundary_coordinate_invalid",
    "planning_boundary_assertion_owner_invalid": "planning_boundary_assertion_owner_invalid",
    "planning_boundary_contract_required": "planning_boundary_contract_required",
    "planning_boundary_binding_conflict": "planning_boundary_binding_conflict",

    "planning_coverage_completion_goal_invalid": "planning_coverage_completion_goal_invalid",
    "planning_coverage_completion_unlinked_point": "planning_coverage_completion_unlinked_point",
    "planning_coverage_completion_owner_invalid": "planning_coverage_completion_owner_invalid",
    "planning_primary_binding_conflict": "planning_primary_binding_conflict",
    "planning_primary_binding_unavailable": "planning_primary_binding_unavailable",
    "planning_primary_feature_invalid": "planning_primary_feature_invalid",
    "planning_primary_source_missing": "planning_primary_source_missing",
    "planning_point_sources_required": "planning_point_sources_required",
    "planning_point_scenario_required": "planning_point_scenario_required",

    "planning_coverage_ambiguous_claim": "planning_coverage_ambiguous_claim",
    "planning_coverage_basis_invalid": "planning_coverage_basis_invalid",
    "planning_coverage_existing_point_changed": "planning_coverage_existing_point_changed",
    "planning_coverage_feature_reference_invalid": "planning_coverage_feature_reference_invalid",
    "planning_coverage_obligation_changed": "planning_coverage_obligation_changed",
    "planning_coverage_obligation_id_invalid": "planning_coverage_obligation_id_invalid",
    "planning_coverage_obligation_limit": "planning_coverage_obligation_limit",
    "planning_coverage_point_id_duplicate": "planning_coverage_point_id_duplicate",
    "planning_coverage_point_ownership_invalid": "planning_coverage_point_ownership_invalid",
    "planning_coverage_point_reference_invalid": "planning_coverage_point_reference_invalid",
    "planning_duplicate_suggestion_invalid": "planning_duplicate_suggestion_invalid",

    "planning_source_reference_invalid": "planning_source_reference_invalid",
    "audit_expectations_not_covered": "audit_expectations_not_covered",
    "audit_quote_not_in_original_source": "audit_quote_not_in_original_source",
    "authorized_modification_changed_step_shape": "authorized_modification_changed_step_shape",
    "duplicate_planning_identity": "duplicate_planning_identity",
    "duplicate_repair_slot_invalid": "duplicate_repair_slot_invalid",
    "empty_case_operations_or_expectations": "empty_case_operations_or_expectations",
    "empty_case_title_or_setup": "empty_case_title_or_setup",
    "invalid_audit_replacement": "invalid_audit_replacement",
    "invalid_feature_reference": "invalid_feature_reference",
    "invalid_source_reference": "invalid_source_reference",
    "operation_without_observable_expectation": "operation_without_observable_expectation",
    "prior_session_probe_missing": "prior_session_probe_missing",
    "required_logout_action_missing": "required_logout_action_missing",
    "required_session_invalidation_missing": "required_session_invalidation_missing",
    "reserved_reuse_binding_invalid": "reserved_reuse_binding_invalid",
    "reserved_reuse_budget_required": "reserved_reuse_budget_required",
    "reserved_reuse_budget_uncovered_points": "reserved_reuse_budget_uncovered_points",
    "reserved_reuse_duplicate_output": "reserved_reuse_duplicate_output",
    "reserved_reuse_output_count_mismatch": "reserved_reuse_output_count_mismatch",
    "reserved_reuse_plan_changed": "reserved_reuse_plan_changed",
    "reserved_reuse_source_revoked": "reserved_reuse_source_revoked",
    "reuse_plan_changed_reanalyze_required": "reuse_plan_changed_reanalyze_required",
    "stage_slot_mismatch": "stage_slot_mismatch",
    "supported_audit_has_replacement": "supported_audit_has_replacement",
    "vague_test_validation": "vague_test_validation",

    "reserved_reuse_mapping_requires_clarification": "reserved_reuse_mapping_requires_clarification",
    "reserved_reuse_selection_conflict": "reserved_reuse_selection_conflict",
    "reserved_source_point_identity_conflict": "reserved_source_point_identity_conflict",'Planning revision has dangling feature references': 'planning_revision_dangling_features',
 'Planning revision references unknown prior IDs': 'planning_revision_unknown_prior_ids',
 'asset_object_match_concurrency_invalid': 'asset_object_match_concurrency_invalid',
 'asset_object_match_duplicate_source': 'asset_object_match_duplicate_source',
 'asset_object_match_scope_invalid': 'asset_object_match_scope_invalid',
 'delete_only_revision_generated_content': 'delete_only_revision_generated_content',
 'delete_only_revision_requires_explicit_removals': 'delete_only_revision_requires_explicit_removals',
 'embedding_provider_unavailable': 'embedding_provider_unavailable',
 'image_attachments_too_large': 'image_attachments_too_large',
 'invalid_knowledge_storage_key': 'invalid_knowledge_storage_key',
 'output_obligation_count_conflict': 'output_obligation_count_conflict',
 'output_obligation_count_mismatch': 'output_obligation_count_mismatch',
 'output_obligation_new_count_conflict': 'output_obligation_new_count_conflict',
 'output_obligation_new_count_mismatch': 'output_obligation_new_count_mismatch',
 'output_obligation_plan_changed': 'output_obligation_plan_changed',
 'planning_budget_requires_smaller_scope': 'planning_budget_requires_smaller_scope',
 'planning_duplicate_test_point': 'planning_duplicate_test_point',
 'planning_feature_reference_invalid': 'planning_feature_reference_invalid',
 'planning_final_point_count_mismatch': 'planning_final_point_count_mismatch',
 'planning_has_no_features': 'planning_has_no_features',
 'planning_has_no_test_points': 'planning_has_no_test_points',
 'planning_point_batch_size_invalid': 'planning_point_batch_size_invalid',
 'required_reuse_coverage_missing_replan_required': 'required_reuse_coverage_missing_replan_required',
 'required_reuse_output_missing_or_duplicate': 'required_reuse_output_missing_or_duplicate',
 'required_reuse_source_invalid': 'required_reuse_source_invalid',
 '单条用例及完整资料超过改写输入预算，请缩小本次资料范围': 'rewrite_input_budget_exceeded',
 '单条用例过大，无法完整核对资料，请缩小用例内容': 'rewrite_case_exceeds_context_budget',
 '单次最多支持500条用例或500个测试点，请缩小范围后重试': 'quantity_limit_exceeded',
 '当前用例快照包含重复标识，请刷新后重试': 'quantity_duplicate_case_identity',
 '批量改写不能改变用例标识': 'rewrite_case_identity_changed',
 '批量改写包含不允许修改的字段': 'rewrite_field_not_allowed',
 '批量改写返回的用例范围与已确认范围不一致': 'rewrite_case_scope_mismatch',
 '改写新增来源不在本次原始资料中': 'rewrite_source_outside_original',
 '改写来源索引不在本次原始资料中': 'rewrite_source_index_outside_original',
 '数量范围包含重复或不存在的用例': 'quantity_scope_invalid',
 '本轮新增及复用输出合计超过500条': 'generation_output_limit_exceeded',
 '来源核对改变了规划用例身份或数量，请重试': 'grounding_changed_case_identity_or_count',
 '补足总量需要当前用例快照，请刷新后重试': 'quantity_current_snapshot_required',
 '规划生成包含范围之外的测试点，请重试': 'generation_point_outside_scope',
 '规划生成批次数量不符，请重试': 'generation_batch_count_mismatch',
 '规划生成遗漏或错误引用测试点，请重试': 'generation_point_coverage_invalid'}

HARNESS_CODES = frozenset([
    "short_reuse_point_receipt",
    "short_reuse_candidate_count",
    "short_reuse_original_snapshot",
    "short_reuse_gap_provenance",
    "short_reuse_adoption_exact_source",

    "short_reuse_pending_clarification",'adoption_candidate_id_missing',
 'adoption_candidate_not_canonically_selected',
 'adoption_candidate_version_missing',
 'adoption_left_stale_candidate_selection',
 'adoption_quantity_mismatch',
 'adoption_selection_version_not_advanced',
 'asset_query_created_candidates',
 'automatic_query_did_not_observe_two_adopted_cases',
 'automatic_query_receipt_missing',
 'cancel_operation_not_cancelled',
 'cancel_preview_not_rejected',
 'cancel_worker_dispatched_early',
 'canonical_foreign_changed',
 'canonical_replay_changed_selection',
 'continuation_fabricated_user_authority',
 'continuation_receipts_missing',
 'crud_attachment_case_identity_mismatch',
 'crud_attachment_priority_mismatch',
 'crud_attachment_read_receipt_missing',
 'crud_candidate_quantity_mismatch',
 'crud_collection_changed_before_approval',
 'crud_collection_confirmation_not_idempotent',
 'crud_collection_create_created_cases',
 'crud_collection_entity_identity_changed',
 'crud_collection_mismatched_approval_not_blocked',
 'crud_collection_proposal_mismatch',
 'crud_collection_proposal_receipt_missing',
 'crud_collection_query_mutated',
 'crud_collection_query_receipt_missing',
 'crud_collection_wrong_approval_mutated',
 'crud_delete_change_set_missing',
 'crud_delete_changed_nontarget_membership',
 'crud_delete_preview_not_ready',
 'crud_delete_receipt_missing',
 'crud_delete_replay_restored_case',
 'crud_delete_replay_unexpected_status',
 'crud_delete_scope_count_mismatch',
 'crud_delete_scope_or_revision_mismatch',
 'crud_delete_unexpected_worker',
 'crud_deleted_target_left_in_selection',
 'crud_foreign_guard_changed',
 'crud_generated_quantity_mismatch',
 'crud_generation_brief_missing',
 'crud_generation_destination_mismatch',
 'crud_generation_points_missing',
 'crud_generation_reused_guard',
 'crud_no_match_changed_selection',
 'crud_no_match_created_operation',
 'crud_no_match_query_receipt_missing',
 'crud_old_scope_delete_not_blocked',
 'crud_rename_changed_collection_id',
 'crud_rename_changed_membership',
 'crud_soft_deleted_case_still_visible',
 'delete_assets_or_memberships_changed',
 'delete_audit_count_invalid',
 'delete_canonical_invalid',
 'delete_changed_impact_accepted',
 'delete_collection_visibility_invalid',
 'delete_foreign_changed',
 'delete_impact_invalid',
 'delete_preapproval_write',
 'delete_proposal_invalid',
 'delete_receipt_missing',
 'delete_rejection_failed',
 'delete_replay_changed_result',
 'delete_result_invalid',
 'delete_soft_state_invalid',
 'delete_wrong_payload_accepted',
 'duplicate_continuation_called_provider',
 'duplicate_continuation_not_ignored',
 'durable_brief_review_gate_missing',
 'durable_candidate_review_gate_missing',
 'durable_multistep_plan_missing',
 'durable_plan_cursor_not_terminal',
 'durable_plan_not_completed',
 'durable_run_missing',
 'durable_worker_failed',
 'explicit_stdin_required',
 'final_typed_query_step_missing',
 'foreign_asset_leaked_into_catalog',
 'foreign_case_read_not_denied',
 'foreign_source_revision_changed',
 'gap_identity_invalid',
 'gap_rewrite_changed_foreign_source',
 'generation_brief_missing',
 'generation_quantity_mismatch',
 'generation_test_points_missing',
 'get_triggered_provider_call',
 'image_multiturn_context_failed',
 'image_question_created_candidates',
 'image_understanding_failed',
 'initial_query_receipt_missing',
 'initial_user_authority_duplicated',
 'model_asset_query_missing_source',
 'new_gap_error_case_missing',
 'no_automatic_second_sdk_segment',
 'original_reuse_not_linked',
 'outbox_continuation_scope_mismatch',
 'outbox_delivery_failed',
 'outbox_domain_scope_mismatch',
 'outbox_queue_mismatch',
 'probe_input_mutation',
 'probe_new_gap',
 'probe_original_source',
 'probe_point_coverage',
 'probe_reuse_gap_count',
 'probe_source_fixture',
 'probe_unexpected_provider_stage',
 'probe_unexpected_stage_count',
 'reapply_unexpected_status',
 'rebuilt_backend_not_ready',
 'rebuilt_backend_setting_missing',
 'reuse_adoption_quantity_mismatch',
 'reuse_asset_brief_missing',
 'reuse_asset_review_gate_missing',
 'reuse_asset_scope_invalid',
 'reuse_collection_confirmation_missing',
 'reuse_destination_mismatch',
 'reuse_gap_candidate_quantity_mismatch',
 'reuse_gap_planning_missing',
 'rewrite_not_applied',
 'rewrite_preservation_failed',
 'rewrite_priority_diff_missing',
 'selection_collection_mismatch',
 'selection_count_mismatch',
 'selection_excluded_case_changed',
 'selection_identity_mismatch',
 'selection_membership_mismatch',
 'selection_old_preview_not_retained',
 'selection_own_apply_not_refreshed',
 'selection_preservation_failed',
 'selection_preview_missing',
 'selection_preview_scope_invalid',
 'selection_proposal_not_bound',
 'selection_reference_mismatch',
 'selection_revision_mismatch',
 'selection_rewrite_confirmation_missing',
 'selection_rewrite_not_applied',
 'selection_version_missing',
 'selection_version_not_advanced',
 'selection_workspace_collection_mismatch',
 'semantic_destination_changed',
 'semantic_foreign_guard_changed',
 'semantic_literal_no_match_not_observed',
 'semantic_no_match_changed_selection',
 'semantic_no_match_query_missing',
 'semantic_query_created_write_proposal',
 'semantic_query_wrong_scope',
 'semantic_selection_tool_receipt_missing',
 'short_reuse_asset_audit_write',
 'short_reuse_asset_binding',
 'short_reuse_asset_review',
 'short_reuse_catalog',
 'short_reuse_decisions',
 'short_reuse_destination',
 'short_reuse_formal_write',
 'short_reuse_protocol_status',
 'short_reuse_quantity',
 'short_reuse_replay',
 'short_reuse_requires_fresh_database',
 'short_reuse_source_revision',
 'short_reuse_strategy',
 'short_reuse_unapproved_candidates',
 'short_reuse_worker_status',
 'spreadsheet_adopted_without_review',
 'spreadsheet_adoption_failed',
 'spreadsheet_candidate_changed_before_apply',
 'spreadsheet_candidate_missing',
 'spreadsheet_formal_asset_created_early',
 'spreadsheet_preview_not_ready',
 'spreadsheet_preview_scope_invalid',
 'spreadsheet_provenance_changed',
 'spreadsheet_provenance_missing',
 'spreadsheet_rewrite_failed',
 'spreadsheet_version_unchanged',
 'stale_selection_apply_not_blocked',
 'unexpected_task_dispatch',
 'unselected_revision_changed',
 'workbench_agent_failed',
 'workbench_agent_not_used',
 'worker_fabricated_user_message',
 'worker_task_budget_exhausted',
 'worker_task_failed'])

# Fixed harness safety failures raised directly rather than through require().
HARNESS_CODES = HARNESS_CODES | frozenset({
    'api_request_failed',
    'credential_missing_or_invalid',
    'external_worker_dispatch_blocked',
    'generation_contract_failed',
    'live_permission_required',
    'rewrite_contract_failed',
    'sdk_loop_acceptance_failed',
    'stdin_must_be_noninteractive',
})

PREFIX_CODES = {
    "planning_feature_uncovered:": "planning_feature_uncovered",
    "改写不能改变系统字段：": "rewrite_system_field_forbidden",
    "候选数量不符：本批需要": "generation_batch_count_mismatch",
    "当前已有": "quantity_total_already_reached",
}


def safe_domain_failure(error):
    from workbench_agent_live_acceptance import exception_name

    code = None
    # Never call str(error), repr(error), or serialize arbitrary args/contexts.
    args = getattr(error, "args", ())
    value = args[0] if isinstance(args, tuple) and args and type(args[0]) is str else None
    if value is not None:
        code = DOMAIN_CODES.get(value)
        if code is None and value in HARNESS_CODES:
            code = value
        if code is None:
            code = next((fixed for prefix, fixed in PREFIX_CODES.items()
                         if value.startswith(prefix)), None)
    return {"exception_class": exception_name(error), "code": code or "unclassified_domain_failure"}


def safe_job_failure(job_id, *, session_factory=None):
    """Only inspect the exact server-returned job, while the caller's DB is alive."""
    from workbench_agent_live_acceptance import EXCEPTION_NAMES

    try:
        from casepilot_api.database import get_session_factory
        from casepilot_api.models import GenerationJob, GenerationJobStage
        from sqlalchemy import case, func, select

        factory = session_factory or get_session_factory()
        identifier = UUID(str(job_id))
        with factory() as db:
            # Project scalars/counts in SQL. Do not load business JSON/text into
            # the diagnostic process merely to measure its array lengths.
            plan = GenerationJob.output_payload["test_brief"]["planning"]
            lengths = [case((func.jsonb_typeof(plan[field]) == "array",
                             func.jsonb_array_length(plan[field])), else_=None)
                       for field in ("feature_points", "test_points")]
            row = db.execute(select(GenerationJob.status, GenerationJob.error_code, *lengths)
                             .where(GenerationJob.id == identifier)).one_or_none()
            if row is None:
                return {"lookup": "not_found"}
            raw_status = getattr(row[0], "value", row[0])
            statuses = {"queued", "running", "completed", "failed", "cancelled", "awaiting_input"}
            result = {"lookup": "ok", "status": raw_status if raw_status in statuses else "unknown",
                      "error_class": row[1] if row[1] in EXCEPTION_NAMES else "unknown"}
            count = db.scalar(select(func.count()).select_from(GenerationJobStage).where(
                GenerationJobStage.generation_job_id == identifier))
            if type(count) is int and 0 <= count <= 100000:
                result["persisted_stage_count"] = count
            for field, count in zip(("feature_points", "test_points"), row[2:], strict=True):
                if type(count) is int and 0 <= count <= 100000:
                    result[field + "_count"] = count
            return result
    except Exception:  # noqa: BLE001 -- Never expose lookup errors or replace domain failure.
        return {"lookup": "unavailable"}


def emit_domain_failure(error, emit, *, job_id=None, session_factory=None):
    # Diagnostic bugs, disk/stdout errors, or unavailable DB must not mask the
    # original domain exception that the caller will re-raise unchanged.
    with suppress(Exception):
        event = {"event": "domain_failure", "failure": safe_domain_failure(error)}
        if job_id is not None:
            event["job"] = safe_job_failure(job_id, session_factory=session_factory)
        emit(event)

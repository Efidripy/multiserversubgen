import inspect

from services.telegram_registry import TelegramRegistry


EXPECTED_TELEGRAM_REGISTRY_NAMES = ['database_path', 'normalize_new_customer_email', 'set_admin_draft', 'get_admin_draft', 'clear_admin_draft', 'set_admin_message_draft', 'get_admin_message_draft', 'clear_admin_message_draft', 'set_customer_note_draft', 'get_customer_note_draft', 'clear_customer_note_draft', 'set_support_reply_draft', 'get_support_reply_draft', 'clear_support_reply_draft', 'get_customer_by_email', 'eligible_provisioning_node_count', 'get_transport_preference', 'set_transport_preference', 'get_or_create_identity', 'get_locale', 'set_locale', 'get_preapproval', '_preapproval_from_row', '_preapproval_from_receipt', 'create_existing_customer_preapproval', 'create_new_customer_preapproval', 'activate_preapproval', '_activate_new_customer_preapproval', 'unlink_identity', 'safe_subscription_node_ids', 'enabled_node_ids', 'has_confirmed_enabled_subscription_binding', 'get_customer_access', 'get_interface_window', 'set_interface_window', 'get_notification_preferences', 'toggle_background_notifications', 'toggle_expiry_reminders', 'toggle_traffic_reminders', 'toggle_traffic_reminder_threshold', '_active_telegram_customer', 'create_guest_subscription_link', 'resolve_guest_subscription_link', 'get_guest_subscription_link', '_ensure_primary_logical_device', 'list_logical_devices', 'list_subscription_devices', 'list_customer_subscription_links', 'get_subscription_device', 'create_subscription_device', 'set_subscription_device_label', 'set_subscription_device_draft', 'get_subscription_device_draft', 'clear_subscription_device_draft', 'revoke_subscription_device', 'resolve_subscription_device_email', 'set_logical_device_label', 'set_logical_device_draft', 'get_logical_device_draft', 'clear_logical_device_draft', 'revoke_guest_subscription_link', 'submit_quality_report', 'list_customer_quality_reports', 'list_subscription_token_events', 'list_traffic_reminder_candidates', 'list_customer_traffic_observation_bindings', 'observe_customer_traffic_bindings', 'get_customer_traffic', 'submit_suspended_appeal', 'list_appeals', 'resolve_appeal', 'begin_support_request', 'submit_pending_support_request', 'clear_support_draft', 'list_support_requests', 'list_customer_support_requests', 'resolve_support_request', 'get_service_notice', 'set_service_notice', 'set_service_notice_draft', 'get_service_notice_draft', 'clear_service_notice_draft', 'create_customer', 'create_pending_application', 'request_required_introduction', 'submit_required_introduction', 'submit_introduction', 'list_pending_applications', 'list_blocked_identities', 'get_pending_application', 'approve_new_application', 'approve_existing_application', 'adopt_discovered_existing_application', 'queue_deferred_existing_discovery', 'get_existing_discovery_job', 'recover_existing_discovery_target', 'reject_application', 'block_identity', 'unblock_identity', 'record_unapproved_noop', '_change_unbound_application_state', 'claim_update', 'store_update_responses', 'pending_update_responses', 'mark_update_response_delivered', 'mark_update_processed', 'retry_update_response', 'get_subscription_message_receipt', 'record_subscription_message_delivery', 'set_node_provisioning_policy', 'list_provisioning_jobs', 'list_provisioning_jobs_page', 'clear_terminal_provisioning_history', 'history_overview', 'history_clear_count', 'list_missing_binding_nodes', 'list_customer_operations_page', 'dismissed_operation_ids', 'list_bindings_page', 'list_audit_page', 'clear_customer_operation_history', 'clear_drift_history', 'forget_all_missing_bindings', 'run_history_retention', 'get_provisioning_job', 'reschedule_provisioning_job', 'list_node_provisioning_policies', '_node_bulk_action', '_node_bulk_action_snapshot', 'preview_node_bulk_action', 'begin_node_bulk_action_preview', 'clear_node_bulk_action_preview', 'queue_node_bulk_action', '_customer_node_state_counts', 'customer_node_matrix', 'queue_customer_node_add', 'list_customers', 'get_customer', 'get_customer_telegram_profile', 'get_customer_admin_note', 'get_customer_registration_introduction', 'set_customer_admin_note', '_registered_broadcast_recipient_ids', 'registered_broadcast_recipient_count', 'queue_admin_direct_message', 'queue_registered_broadcast', '_lifecycle_operation_type', '_forget_missing_binding', 'forget_missing_bindings', 'repair_customer', '_customer_operation_snapshot', 'preview_customer_operation', '_node_operation_type', '_customer_node_operation_snapshot', 'preview_customer_node_operation', 'queue_customer_node_operation', '_get_customer_operation_from_conn', 'queue_customer_operation', 'get_customer_operation', 'list_customer_operations', 'reschedule_customer_operation', 'get_admin_dashboard', 'list_attention_items', 'list_customer_tags', 'set_customer_tags', 'list_saved_filters', 'save_filter', 'delete_saved_filter', 'customer_timeline', 'get_customer_read_only_view', 'create_lifecycle_schedule', '_schedule_from_row', 'list_lifecycle_schedules', 'cancel_lifecycle_schedule', 'claim_due_lifecycle_schedule', 'complete_lifecycle_schedule', '_bulk_preview_digest', 'preview_bulk_customer_operations', '_parse_bulk_preview_items', '_insert_bulk_lifecycle_operation', 'queue_bulk_customer_operations', 'get_bulk_lifecycle_status', 'drift_inventory', 'sync_drift_binding_enabled', 'record_drift_findings', 'auto_forget_drift_binding', 'list_drift_findings', 'resolve_drift_finding', '_insert_adopted_binding', 'adopt_drift_binding']

EXPECTED_TRANSFERRED_SIGNATURES = {'claim_update': "(self, *, update_id: 'int', telegram_user_id: 'int | None', update_type: 'str', payload_digest: 'str') -> 'bool'", 'store_update_responses': "(self, *, update_id: 'int', responses: 'list[tuple]') -> 'None'", 'pending_update_responses': "(self, update_id: 'int') -> 'list[tuple[int, int, str, dict[str, Any] | None]]'", 'mark_update_response_delivered': "(self, *, update_id: 'int', response_index: 'int') -> 'None'", 'mark_update_processed': "(self, update_id: 'int') -> 'None'", 'retry_update_response': "(self, *, update_id: 'int', response_index: 'int') -> 'None'", 'get_subscription_message_receipt': "(self, telegram_user_id: 'int') -> 'TelegramSubscriptionMessageReceipt | None'", 'record_subscription_message_delivery': "(self, *, telegram_user_id: 'int', token_digest: 'str', chat_id: 'int', message_id: 'int') -> 'None'", 'get_service_notice': "(self) -> 'TelegramServiceNotice'", 'set_service_notice': "(self, *, body: 'str | None', expected_row_version: 'int', idempotency_key: 'str', updated_by: 'str') -> 'TelegramServiceNotice'"}

EXPECTED_TRANSFERRED_SIGNATURES.update({
    'eligible_provisioning_node_count': "(self) -> 'int'",
    'get_notification_preferences': "(self, telegram_user_id: 'int') -> 'TelegramNotificationPreferences'",
    'toggle_background_notifications': "(self, telegram_user_id: 'int') -> 'TelegramNotificationPreferences'",
    'toggle_expiry_reminders': "(self, telegram_user_id: 'int') -> 'TelegramNotificationPreferences'",
    'toggle_traffic_reminders': "(self, telegram_user_id: 'int') -> 'TelegramNotificationPreferences'",
    'toggle_traffic_reminder_threshold': "(self, telegram_user_id: 'int', threshold_percent: 'int') -> 'TelegramNotificationPreferences'",
    'list_traffic_reminder_candidates': "(self) -> 'tuple[CustomerTrafficQuotaCandidate, ...]'",
    'list_customer_traffic_observation_bindings': "(self) -> 'dict[int, tuple[CustomerTrafficObservationBinding, ...]]'",
    'observe_customer_traffic_bindings': "(self, observations: 'dict[int, dict[tuple[int, int], int]]') -> 'tuple[CustomerTrafficLedger, ...]'",
    'get_customer_traffic': "(self, customer_id: 'int') -> 'CustomerTrafficLedger'",
    'submit_suspended_appeal': "(self, *, telegram_user_id: 'int', body: 'str') -> 'AppealResult'",
    'list_appeals': "(self, *, status: 'str' = 'open', limit: 'int' = 100) -> 'list[AppealAdminItem]'",
    'resolve_appeal': "(self, *, appeal_id: 'int', expected_row_version: 'int', status: 'str', idempotency_key: 'str', resolved_by: 'str') -> 'AppealResolutionResult'",
    'begin_support_request': "(self, *, telegram_user_id: 'int', category: 'str') -> 'None'",
    'submit_pending_support_request': "(self, *, telegram_user_id: 'int', body: 'str') -> 'TelegramSupportRequest | None'",
    'list_support_requests': "(self, *, status: 'str' = 'open', limit: 'int' = 100) -> 'list[TelegramSupportRequest]'",
    'list_customer_support_requests': "(self, customer_id: 'int', *, limit: 'int' = 20) -> 'list[TelegramSupportRequest]'",
    'resolve_support_request': "(self, *, support_request_id: 'int', expected_row_version: 'int', response: 'str | None', idempotency_key: 'str', resolved_by: 'str') -> 'TelegramSupportResolution'",
    'set_admin_draft': "(self, *, admin_telegram_user_id: 'int', action: 'str', telegram_user_id: 'int | None' = None, customer_id: 'int | None' = None, expected_row_version: 'int | None' = None, page: 'int' = 0, value: 'str | None' = None) -> 'TelegramAdminDraft'",
    'get_admin_draft': "(self, admin_telegram_user_id: 'int') -> 'TelegramAdminDraft | None'",
    'clear_admin_draft': "(self, admin_telegram_user_id: 'int') -> 'None'",
    'set_admin_message_draft': "(self, *, admin_telegram_user_id: 'int', mode: 'str', customer_id: 'int | None' = None, page: 'int' = 0, body: 'str | None' = None, photo_file_ids: 'tuple[str, ...] | None' = None, media_group_id: 'str | None' = None) -> 'TelegramAdminMessageDraft'",
    'get_admin_message_draft': "(self, admin_telegram_user_id: 'int') -> 'TelegramAdminMessageDraft | None'",
    'clear_admin_message_draft': "(self, admin_telegram_user_id: 'int') -> 'None'",
    'set_customer_note_draft': "(self, *, admin_telegram_user_id: 'int', customer_id: 'int', page: 'int') -> 'TelegramCustomerNoteDraft'",
    'get_customer_note_draft': "(self, admin_telegram_user_id: 'int') -> 'TelegramCustomerNoteDraft | None'",
    'clear_customer_note_draft': "(self, admin_telegram_user_id: 'int') -> 'None'",
    'set_support_reply_draft': "(self, *, admin_telegram_user_id: 'int', support_request_id: 'int', customer_id: 'int', expected_row_version: 'int', page: 'int', body: 'str | None' = None) -> 'TelegramSupportReplyDraft'",
    'get_support_reply_draft': "(self, admin_telegram_user_id: 'int') -> 'TelegramSupportReplyDraft | None'",
    'clear_support_reply_draft': "(self, admin_telegram_user_id: 'int') -> 'None'",
    'set_subscription_device_draft': "(self, *, telegram_user_id: 'int', subscription_device_id: 'int') -> 'None'",
    'get_subscription_device_draft': "(self, telegram_user_id: 'int') -> 'int | None'",
    'clear_subscription_device_draft': "(self, telegram_user_id: 'int') -> 'None'",
    'set_logical_device_draft': "(self, *, telegram_user_id: 'int', device_id: 'int') -> 'None'",
    'get_logical_device_draft': "(self, telegram_user_id: 'int') -> 'int | None'",
    'clear_logical_device_draft': "(self, telegram_user_id: 'int') -> 'None'",
    'clear_support_draft': "(self, telegram_user_id: 'int') -> 'None'",
    'set_service_notice_draft': "(self, *, admin_telegram_user_id: 'int', expected_row_version: 'int') -> 'TelegramServiceNoticeDraft'",
    'get_service_notice_draft': "(self, admin_telegram_user_id: 'int') -> 'TelegramServiceNoticeDraft | None'",
    'clear_service_notice_draft': "(self, admin_telegram_user_id: 'int') -> 'None'",
})

EXPECTED_TRANSFERRED_SIGNATURES.update({
    'create_guest_subscription_link': "(self, *, telegram_user_id: 'int', duration_hours: 'int') -> 'TelegramGuestSubscriptionLink'",
    'resolve_guest_subscription_link': "(self, token: 'str') -> 'TelegramGuestSubscriptionLink | None'",
    'get_guest_subscription_link': "(self, *, telegram_user_id: 'int', guest_link_id: 'int') -> 'TelegramGuestSubscriptionLink'",
    '_ensure_primary_logical_device': "(self, conn: 'sqlite3.Connection', customer_id: 'int') -> 'None'",
    'list_logical_devices': "(self, telegram_user_id: 'int', *, include_inactive: 'bool' = True) -> 'tuple[TelegramLogicalDevice, ...]'",
    'list_subscription_devices': "(self, telegram_user_id: 'int') -> 'tuple[TelegramSubscriptionDevice, ...]'",
    'list_customer_subscription_links': "(self, customer_id: 'int') -> 'tuple[TelegramCustomerSubscriptionLink, ...]'",
    'get_subscription_device': "(self, *, telegram_user_id: 'int', subscription_device_id: 'int') -> 'TelegramSubscriptionDevice'",
    'create_subscription_device': "(self, *, telegram_user_id: 'int', label: 'str') -> 'TelegramSubscriptionDevice'",
    'set_subscription_device_label': "(self, *, telegram_user_id: 'int', subscription_device_id: 'int', label: 'str') -> 'TelegramSubscriptionDevice'",
    'revoke_subscription_device': "(self, *, telegram_user_id: 'int', subscription_device_id: 'int') -> 'None'",
    'resolve_subscription_device_email': "(self, token_identifier: 'str') -> 'str | None'",
    'set_logical_device_label': "(self, *, telegram_user_id: 'int', device_id: 'int', label: 'str') -> 'TelegramLogicalDevice'",
    'revoke_guest_subscription_link': "(self, *, telegram_user_id: 'int', guest_link_id: 'int') -> 'None'",
    'submit_quality_report': "(self, *, telegram_user_id: 'int', kind: 'str', platform: 'str') -> 'TelegramQualityReport'",
    'list_customer_quality_reports': "(self, customer_id: 'int', *, limit: 'int' = 5) -> 'tuple[TelegramQualityReport, ...]'",
    'list_subscription_token_events': "(self, customer_id: 'int', *, limit: 'int' = 5) -> 'tuple[TelegramSubscriptionTokenEvent, ...]'",
})


def test_telegram_registry_public_methods_are_stable():
    actual = [name for name in vars(TelegramRegistry) if not name.startswith("__")]
    assert actual == EXPECTED_TELEGRAM_REGISTRY_NAMES


def test_transferred_method_signatures_are_stable():
    for name, expected in EXPECTED_TRANSFERRED_SIGNATURES.items():
        assert str(inspect.signature(getattr(TelegramRegistry, name))) == expected

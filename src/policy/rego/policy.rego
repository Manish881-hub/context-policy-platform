package isp.policy

# Mirrors src/policy/engine.py — same inputs, same outputs.
# Input: {identity: {technician_id, queue_origin}, resource: {subscriber_id}, action, gps_verified_on_site, field_checkin_active, site_id, subscriber_site_id, ticket_id}
# Output: {allowed, reason, policy_id, redact}

default allow := false
default redact := false

# WiFi credentials — field_app allow only if GPS+checkin+site match
allow if {
    input.action == "get_wifi_credentials"
    input.identity.queue_origin == "field_app"
    input.field_checkin_active == true
    input.gps_verified_on_site == true
    not site_mismatch
}

allow if {
    input.action == "get_wifi_credentials"
    input.identity.queue_origin == "support_authorized"
    input.ticket_id != null
    input.ticket_id != ""
}

# Line status / profile / OLT aggregate — broader (no PSK)
allow if {
    input.action == "get_line_status"
    input.identity.queue_origin != "support_unauthorized"
}

allow if {
    input.action == "get_subscriber_profile"
    input.identity.queue_origin != "support_unauthorized"
}

allow if {
    input.action == "get_olt_subscribers"
    input.identity.queue_origin != "support_unauthorized"
}

# Reset ONT — write, strict like wifi + ticket required
allow if {
    input.action == "reset_ont"
    input.identity.queue_origin == "field_app"
    input.field_checkin_active == true
    input.gps_verified_on_site == true
    not site_mismatch
    input.ticket_id != null
    input.ticket_id != ""
}

allow if {
    input.action == "reset_ont"
    input.identity.queue_origin == "support_authorized"
    input.ticket_id != null
    input.ticket_id != ""
}

allow if {
    input.action == "query_docs"
    input.identity.queue_origin != "support_unauthorized"
}

allow if {
    input.action == "query_sql"
    input.identity.queue_origin == "field_app"
    input.field_checkin_active == true
    input.gps_verified_on_site == true
    not site_mismatch
}

allow if {
    input.action == "query_sql"
    input.identity.queue_origin == "support_authorized"
    input.ticket_id != null
}

# Redact for self-service (profile/docs/sql aggregate without PSK leak)
redact if {
    input.identity.queue_origin == "self_service"
    input.action in {"query_docs", "query_sql", "get_subscriber_profile"}
}

site_mismatch if {
    input.site_id != null
    input.subscriber_site_id != null
    input.site_id != input.subscriber_site_id
}

# Deny reasons (for audit, use policy_id)
policy_id := "wifi-allow-field-onsite" if {
    input.action == "get_wifi_credentials"
    input.identity.queue_origin == "field_app"
    allow
} else := "wifi-allow-support-ticket" if {
    input.action == "get_wifi_credentials"
    input.identity.queue_origin == "support_authorized"
    allow
} else := "reset-allow-field-onsite" if {
    input.action == "reset_ont"
    input.identity.queue_origin == "field_app"
    allow
} else := "reset-allow-support-ticket" if {
    input.action == "reset_ont"
    input.identity.queue_origin == "support_authorized"
    allow
} else := "sql-allow-field-onsite" if {
    input.action == "query_sql"
    input.identity.queue_origin == "field_app"
    allow
} else := "docs-allow-redact" if {
    redact
} else := "profile-allow" if {
    input.action == "get_subscriber_profile"
    allow
} else := "olt-allow" if {
    input.action == "get_olt_subscribers"
    allow
} else := "default-deny"

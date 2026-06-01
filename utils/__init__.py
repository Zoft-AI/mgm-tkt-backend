"""
Utils Package
"""

from .common import (
    safe_json_loads,
    safe_json_dumps,
    validate_email,
    validate_password_strength,
    sanitize_input,
    format_datetime,
    parse_datetime,
    get_current_utc_timestamp,
    chunk_list,
    merge_dicts,
    truncate_string,
    is_valid_uuid,
    generate_slug,
    format_file_size
)

from .security import (
    validate_file_security,
    sanitize_filename,
    validate_file_path,
    mask_sensitive_data,
    validate_session_id
)

from .database import (
    get_db,
    get_redis_client,
    db_manager,
    cache_manager,
    record_to_dict,
    records_to_list,
)

__all__ = [
    "safe_json_loads",
    "safe_json_dumps",
    "validate_email",
    "validate_password_strength",
    "sanitize_input",
    "format_datetime",
    "parse_datetime",
    "get_current_utc_timestamp",
    "chunk_list",
    "merge_dicts",
    "truncate_string",
    "is_valid_uuid",
    "generate_slug",
    "format_file_size",
    "validate_file_security",
    "sanitize_filename",
    "validate_file_path",
    "mask_sensitive_data",
    "validate_session_id",
    "get_db",
    "get_redis_client",
    "db_manager",
    "cache_manager",
    "record_to_dict",
    "records_to_list",
]

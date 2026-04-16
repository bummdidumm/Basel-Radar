def determine_change_type(f: dict, known_file_details: dict, is_initial: bool) -> str:
    """
    Evaluates file metadata to determine the exact change type.
    Must return: NEW, UPDATED, RENAMED, MOVED, DELETED, TRASHED, REMOVED_OR_NO_ACCESS
    """
    if is_initial:
        return "NEW"

    file_id = f.get("id")
    removed = f.get("removed", False)
    trashed = f.get("trashed", False)

    # 1. DELETED
    if removed and f.get("explicitly_trashed_or_deleted_flag", False):
        return "DELETED"

    # 2. TRASHED
    if trashed:
        return "TRASHED"

    # 3a. MOVED_OUT_OF_SCOPE: file exists in Drive but was moved outside the target folder tree.
    # Synthetic flag set by fetch_delta_chunk() when is_in_target_folder() returns False.
    if removed and f.get("scope_exit"):
        return "MOVED_OUT_OF_SCOPE"

    # 3. REMOVED_OR_NO_ACCESS
    # Removed true but not explicitly deleted (e.g., access revoked)
    if removed:
        return "REMOVED_OR_NO_ACCESS"

    # 4. NEW
    if file_id not in known_file_details:
        return "NEW"

    cached = known_file_details.get(file_id, {})

    cached_name = cached.get("name")
    current_name = f.get("name")
    name_changed = (cached_name and cached_name != current_name)

    cached_parents_sorted_str = cached.get("parent_ids_sorted", "")
    current_parents_sorted_str = ",".join(sorted(f.get("parents", [])))
    parents_changed = (current_parents_sorted_str != cached_parents_sorted_str)

    # 5/6. MOVED / RENAMED
    # Gemäß Zielschema gibt es nur "MOVED" oder "RENAMED".
    # Hat sich das Parent geändert, ist es MOVED. Falls sich auch der Name geändert hat,
    # dominiert MOVED (oder man löst es beliebig auf).
    if parents_changed:
        return "MOVED"
    if name_changed:
        return "RENAMED"

    # 8. UPDATED (Inhalt geändert)
    current_md5 = f.get("md5Checksum")
    cached_md5 = cached.get("md5")
    if current_md5 and cached_md5 and current_md5 != cached_md5:
        return "UPDATED"

    current_size = str(f.get("size", "0"))
    cached_size = str(cached.get("size_bytes", "0"))
    if current_size != cached_size:
        return "UPDATED"

    # Zusätzlich: Check Timestamp-Veränderungen bei Google-native Dateien ohne MD5
    current_time = f.get("modifiedTime")
    cached_time = cached.get("updated_at")
    if current_time and cached_time and current_time != cached_time:
        return "UPDATED"

    # 9. UNCHANGED_CONTENT_METADATA_ONLY
    # Fallback, falls Metadaten-Update vorliegt (z.B. Beschreibung/Sternchen),
    # aber weder Name noch Path, Hash oder Size abweichen.
    return "UNCHANGED_CONTENT_METADATA_ONLY"

def check_md5_size_prefilter(f: dict, known_file_details: dict) -> bool:
    """True = Content definitely unchanged (Size and MD5 match exactly)."""
    file_id = f.get("id")
    if file_id not in known_file_details:
        return False

    mime_type = f.get("mimeType", "")
    if mime_type.startswith("application/vnd.google-apps"):
        return False # No MD5 for native formats

    current_md5 = f.get("md5Checksum")
    current_size = str(f.get("size", "0"))

    cached = known_file_details.get(file_id, {})
    cached_md5 = cached.get("md5")
    cached_size = str(cached.get("size_bytes", "0"))

    if current_md5 and cached_md5 and current_md5 == cached_md5 and current_size == cached_size:
        return True

    return False

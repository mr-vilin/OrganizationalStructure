from app.stores.domain import StorePatch, validate_store_changes


def test_store_code_is_trimmed_and_empty_code_becomes_none():
    changes = validate_store_changes(
        [StorePatch("DepA", True, "  AbC-1  ", " note "), StorePatch("DepB", False, "   ", None)],
        departments={"DepA": {"status": "active", "is_virtual_root": False}, "DepB": {"status": "active", "is_virtual_root": False}},
    )
    assert changes[0].store_code == "AbC-1"
    assert changes[1].store_code is None


def test_virtual_root_and_inactive_department_cannot_be_new_stores():
    departments = {"Root": {"status": "active", "is_virtual_root": True}, "Old": {"status": "inactive", "is_virtual_root": False}}

    errors = validate_store_changes([StorePatch("Root", True), StorePatch("Old", True)], departments=departments, raise_errors=False)

    assert [(error.department_id, error.code) for error in errors] == [("Root", "VIRTUAL_ROOT"), ("Old", "DEPARTMENT_INACTIVE")]


def test_duplicate_codes_are_case_sensitive_but_exact_duplicates_are_rejected():
    departments = {key: {"status": "active", "is_virtual_root": False} for key in ("A", "B", "C")}

    errors = validate_store_changes(
        [StorePatch("A", True, "Shop"), StorePatch("B", True, "shop"), StorePatch("C", True, "Shop")],
        departments=departments,
        raise_errors=False,
    )

    assert [(error.department_id, error.code) for error in errors] == [("C", "DUPLICATE_STORE_CODE")]

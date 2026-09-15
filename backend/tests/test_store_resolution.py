from app.directory.domain import Department, Employee, Membership, resolve_employee_stores


def test_nearest_store_is_selected_for_each_membership_without_duplicates():
    departments = {
        "hq": Department("hq", None, False),
        "north": Department("north", "hq", True),
        "kitchen": Department("kitchen", "north", False),
        "station": Department("station", "kitchen", True),
    }
    employee = Employee("u1", "active", "kitchen")
    memberships = [Membership("u1", "kitchen"), Membership("u1", "station")]

    result = resolve_employee_stores(employee, memberships, departments)

    assert result.store_ids == ["north", "station"]
    assert result.primary_store_id == "north"
    assert result.primary_store_status == "resolved"


def test_headquarters_primary_department_does_not_promote_part_time_store():
    departments = {
        "hq": Department("hq", None, False),
        "university": Department("university", "hq", True),
    }
    employee = Employee("u1", "active", "hq")
    memberships = [Membership("u1", "hq"), Membership("u1", "university")]

    result = resolve_employee_stores(employee, memberships, departments)

    assert result.store_ids == ["university"]
    assert result.primary_store_id is None
    assert result.primary_store_status == "not_in_store"


def test_missing_ancestor_makes_primary_store_unknown_but_keeps_other_store():
    departments = {"shop": Department("shop", None, True), "orphan": Department("orphan", "missing", False)}
    employee = Employee("u1", "active", "orphan")
    memberships = [Membership("u1", "orphan"), Membership("u1", "shop")]

    result = resolve_employee_stores(employee, memberships, departments)

    assert result.store_ids == ["shop"]
    assert result.primary_store_status == "unknown"


def test_inactive_employee_has_no_current_store_assignment():
    departments = {"shop": Department("shop", None, True)}
    employee = Employee("u1", "inactive", "shop")

    result = resolve_employee_stores(employee, [Membership("u1", "shop")], departments)

    assert result.store_ids == []
    assert result.primary_store_status == "inactive"


def test_primary_department_must_be_an_active_membership():
    departments = {"a": Department("a", None, True), "b": Department("b", None, True)}
    employee = Employee("u1", "active", "a")

    result = resolve_employee_stores(employee, [Membership("u1", "b")], departments)

    assert result.store_ids == ["b"]
    assert result.primary_store_status == "inconsistent"


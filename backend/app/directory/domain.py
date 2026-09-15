from dataclasses import dataclass


@dataclass(frozen=True)
class Department:
    id: str
    parent_id: str | None
    is_store: bool
    status: str = "active"
    sync_quality: str = "complete"


@dataclass(frozen=True)
class Employee:
    id: str
    status: str
    primary_department_id: str | None
    sync_quality: str = "complete"


@dataclass(frozen=True)
class Membership:
    employee_id: str
    department_id: str
    active: bool = True


@dataclass(frozen=True)
class StoreResolution:
    store_ids: list[str]
    primary_store_id: str | None
    primary_store_status: str


def _nearest_store(department_id: str, departments: dict[str, Department]) -> tuple[str | None, bool]:
    current_id: str | None = department_id
    visited: set[str] = set()
    while current_id is not None:
        if current_id in visited:
            return None, False
        visited.add(current_id)
        department = departments.get(current_id)
        if department is None:
            return None, False
        if department.status!='active':
            return None, False
        if department.sync_quality in {"pending_verification", "unknown", "inconsistent"}:
            return None, False
        if department.status == "active" and department.is_store:
            return department.id, True
        current_id = department.parent_id
    return None, True


def resolve_employee_stores(
    employee: Employee,
    memberships: list[Membership],
    departments: dict[str, Department],
) -> StoreResolution:
    if employee.status != "active":
        return StoreResolution([], None, "inactive")

    active_department_ids = [
        relation.department_id
        for relation in memberships
        if relation.active and relation.employee_id == employee.id
    ]
    stores: list[str] = []
    for department_id in active_department_ids:
        store_id, _ = _nearest_store(department_id, departments)
        if store_id is not None and store_id not in stores:
            stores.append(store_id)

    primary = employee.primary_department_id
    if employee.sync_quality == "inconsistent":
        return StoreResolution(stores, None, "inconsistent")
    if primary is None:
        return StoreResolution(stores, None, "unknown")
    if primary in departments and departments[primary].status!='active':
        return StoreResolution(stores,None,'unknown')
    if primary not in active_department_ids:
        return StoreResolution(stores, None, "inconsistent")
    primary_store, complete = _nearest_store(primary, departments)
    if not complete:
        return StoreResolution(stores, None, "unknown")
    if primary_store is None:
        return StoreResolution(stores, None, "not_in_store")
    return StoreResolution(stores, primary_store, "resolved")

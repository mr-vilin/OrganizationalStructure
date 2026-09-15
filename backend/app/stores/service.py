from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.directory.domain import Department as DomainDepartment
from app.directory.domain import Employee as DomainEmployee
from app.directory.domain import Membership, resolve_employee_stores
from app.persistence.models import ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreCodeReservation, StoreProfile

from .domain import InvalidStoreChanges, StorePatch, StoreValidationError, merge_store_patch, validate_store_changes


class StoreAdminService:
    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    def preview(self, changes: list[StorePatch], expected_version: int) -> dict:
        with self._sessions() as db, db.begin():
            state = self._lock_state(db, expected_version, lock=False)
            normalized = self._validate(db, changes)
            before_projection = self._projection(db)
            after_projection = self._projection(db, {c.department_id: c.is_store for c in normalized})
            affected = sum(before_projection[key] != value for key, value in after_projection.items())
            concrete = []
            for change in normalized:
                after = merge_store_patch(self._snapshot(db.get(StoreProfile, change.department_id)), change)
                concrete.append({"department_id": change.department_id, **after})
            return {"data_version": state.data_version, "changes": concrete, "affected_employee_count": affected}

    def apply(self, changes: list[StorePatch], expected_version: int, actor: str, now: datetime) -> dict:
        with self._sessions.begin() as db:
            state = self._lock_state(db, expected_version, lock=True)
            normalized = self._validate(db, changes)
            business_changes = 0
            for change in normalized:
                current = db.get(StoreProfile, change.department_id)
                before = self._snapshot(current)
                after = merge_store_patch(before, change)
                if before == after:
                    continue
                if after["store_code"]:
                    reservation = db.get(StoreCodeReservation, after["store_code"])
                    if reservation and reservation.department_id != change.department_id:
                        raise InvalidStoreChanges([StoreValidationError(change.department_id, "STORE_CODE_RESERVED", "门店编码已由其他部门保留")])
                    if reservation is None:
                        db.add(StoreCodeReservation(store_code=after["store_code"], department_id=change.department_id, reserved_at=now))
                if current is None:
                    current = StoreProfile(department_id=change.department_id)
                    db.add(current)
                current.is_store, current.store_code, current.notes = after["is_store"], after["store_code"], after["notes"]
                db.add(ChangeLog(object_type="store", object_id=change.department_id, source="admin", actor=actor, before_data=before, after_data=after, committed_at=now))
                business_changes += 1
            if business_changes:
                db.flush()
                self._rebuild_projection(db)
                state.data_version += 1
            return {"data_version": state.data_version, "changed_count": business_changes}

    def _validate(self, db: Session, changes: list[StorePatch]) -> list[StorePatch]:
        ids = [change.department_id for change in changes]
        departments = {row.id: {"status": row.status, "is_virtual_root": row.is_virtual_root} for row in db.scalars(select(Department).where(Department.id.in_(ids)))}
        normalized = validate_store_changes(changes, departments=departments)
        errors = []
        for change in normalized:
            current = self._snapshot(db.get(StoreProfile, change.department_id))
            code = merge_store_patch(current, change)["store_code"]
            reservation = db.get(StoreCodeReservation, code) if code else None
            if reservation is not None and reservation.department_id != change.department_id:
                errors.append(StoreValidationError(change.department_id, "STORE_CODE_RESERVED", "门店编码已由其他部门保留"))
        if errors:
            raise InvalidStoreChanges(errors)
        return normalized

    @staticmethod
    def _lock_state(db: Session, expected_version: int, lock: bool) -> DatasetState:
        stmt = select(DatasetState).where(DatasetState.id == 1)
        state = db.scalar(stmt.with_for_update() if lock else stmt)
        if state is None:
            raise RuntimeError("INITIALIZATION_INCOMPLETE")
        if state.data_version != expected_version:
            raise RuntimeError("DATASET_CHANGED")
        return state

    @staticmethod
    def _snapshot(profile: StoreProfile | None) -> dict:
        return {"is_store": bool(profile and profile.is_store), "store_code": profile.store_code if profile else None, "notes": profile.notes if profile else None}

    @staticmethod
    def _projection(db, overrides=None):
        store_ids = set(db.scalars(select(StoreProfile.department_id).where(StoreProfile.is_store.is_(True))))
        for identifier, enabled in (overrides or {}).items():
            if enabled:
                store_ids.add(identifier)
            else:
                store_ids.discard(identifier)
        departments = {row.id: DomainDepartment(row.id, row.parent_id, row.id in store_ids, row.status, row.sync_quality) for row in db.scalars(select(Department))}
        relations = list(db.scalars(select(EmployeeDepartment)))
        by_employee: dict[str, list[Membership]] = {}
        for relation in relations:
            by_employee.setdefault(relation.employee_id, []).append(Membership(relation.employee_id, relation.department_id, relation.active))
        projection = {}
        for employee in db.scalars(select(Employee)):
            memberships = by_employee.get(employee.id, [])
            result = resolve_employee_stores(DomainEmployee(employee.id, employee.status, employee.primary_department_id, employee.sync_quality), memberships, departments)
            paths = {}
            for relation in memberships:
                if not relation.active:
                    continue
                path, current, visited = [], relation.department_id, set()
                while current is not None and current not in visited:
                    visited.add(current)
                    department = departments.get(current)
                    if department is None or department.status!='active' or department.sync_quality in {'unknown', 'pending_verification', 'inconsistent'}:
                        break
                    path.append(current)
                    if current in result.store_ids:
                        if current not in paths or relation.department_id == employee.primary_department_id:
                            paths[current] = path
                        break
                    current = department.parent_id
            projection[employee.id] = (result, paths)
        return projection

    @staticmethod
    def _rebuild_projection(db: Session) -> None:
        projection = StoreAdminService._projection(db)
        db.execute(delete(EmployeeStore))
        for employee in db.scalars(select(Employee)):
            result, paths = projection[employee.id]
            employee.primary_store_status = result.primary_store_status
            for store_id in result.store_ids:
                db.add(EmployeeStore(employee_id=employee.id, store_id=store_id, is_primary=store_id == result.primary_store_id, path=paths.get(store_id, [])))

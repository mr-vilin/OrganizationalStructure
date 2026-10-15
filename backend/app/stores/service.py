from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.directory.domain import Department as DomainDepartment
from app.directory.domain import Employee as DomainEmployee
from app.directory.domain import Membership, resolve_employee_stores
from app.persistence.models import ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreCodeReservation, StoreProfile

from .domain import InvalidStoreChanges, StorePatch, StoreValidationError, merge_store_patch, validate_store_changes


@dataclass(frozen=True)
class StoreApplyResult:
    """供事务调用方直接关联本次写入的版本与完整审计标识。"""
    dataset_epoch: str
    data_version: int
    changed_count: int
    audit_ids: tuple[int, ...]


class StoreAdminService:
    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    def preview(self, changes: list[StorePatch], expected_version: int) -> dict:
        with self._sessions() as db, db.begin():
            return self.preview_in_session(db, changes, expected_version)

    def preview_in_session(self, db: Session, changes: list[StorePatch], expected_version: int) -> dict:
        state = self._lock_state(db, expected_version, lock=False)
        normalized = self._validate(db, changes)
        before_projection = self._projection(db)
        after_projection = self._projection(db, {c.department_id: c.is_store for c in normalized})
        affected = sum(before_projection[key] != value for key, value in after_projection.items())
        concrete = []
        for change in normalized:
            after = merge_store_patch(self._snapshot(db.get(StoreProfile, change.department_id, populate_existing=True)), change)
            concrete.append({"department_id": change.department_id, **after})
        return {"data_version": state.data_version, "changes": concrete, "affected_employee_count": affected}

    def apply(self, changes: list[StorePatch], expected_version: int, actor: str, now: datetime) -> dict:
        with self._sessions.begin() as db:
            result = self.apply_in_session(db, changes, expected_version, actor, now)
            return {"data_version": result.data_version, "changed_count": result.changed_count}

    def apply_in_session(self, db: Session, changes: list[StorePatch], expected_version: int, actor: str, now: datetime) -> StoreApplyResult:
        state = self._lock_state(db, expected_version, lock=True)
        normalized = self._validate(db, changes, current_read=True)
        audit_rows = []
        business_changes = 0
        for change in normalized:
            current = db.scalar(self._read_statement(select(StoreProfile).where(StoreProfile.department_id == change.department_id), True))
            before = self._snapshot(current)
            after = merge_store_patch(before, change)
            if before == after:
                continue
            if after["store_code"]:
                reservation = db.scalar(self._read_statement(select(StoreCodeReservation).where(StoreCodeReservation.store_code == after["store_code"]), True))
                if reservation and reservation.department_id != change.department_id:
                    raise InvalidStoreChanges([StoreValidationError(change.department_id, "STORE_CODE_RESERVED", "门店编码已由其他部门保留")])
                if reservation is None:
                    db.add(StoreCodeReservation(store_code=after["store_code"], department_id=change.department_id, reserved_at=now))
            if current is None:
                current = StoreProfile(department_id=change.department_id)
                db.add(current)
            current.is_store, current.store_code, current.notes = after["is_store"], after["store_code"], after["notes"]
            audit = ChangeLog(object_type="store", object_id=change.department_id, source="admin", actor=actor, before_data=before, after_data=after, committed_at=now)
            db.add(audit)
            audit_rows.append(audit)
            business_changes += 1
        if business_changes:
            db.flush()
            self._rebuild_projection(db)
            state.data_version += 1
        db.flush()
        return StoreApplyResult(state.dataset_epoch, state.data_version, business_changes, tuple(row.id for row in audit_rows))

    @staticmethod
    def _read_statement(statement, current_read: bool):
        # 写路径已持有 DatasetState 锁；FOR UPDATE 绕过调用方事务已有的 RR Read View，
        # populate_existing 同时刷新 ORM identity map，二者缺一不可。
        return (statement.with_for_update() if current_read else statement).execution_options(populate_existing=True)

    def _validate(self, db: Session, changes: list[StorePatch], *, current_read: bool = False) -> list[StorePatch]:
        ids = [change.department_id for change in changes]
        departments = {row.id: {"status": row.status, "is_virtual_root": row.is_virtual_root} for row in db.scalars(self._read_statement(select(Department).where(Department.id.in_(ids)), current_read))}
        normalized = validate_store_changes(changes, departments=departments)
        errors = []
        for change in normalized:
            current = self._snapshot(db.scalar(self._read_statement(select(StoreProfile).where(StoreProfile.department_id == change.department_id), current_read)))
            code = merge_store_patch(current, change)["store_code"]
            reservation = db.scalar(self._read_statement(select(StoreCodeReservation).where(StoreCodeReservation.store_code == code), current_read)) if code else None
            if reservation is not None and reservation.department_id != change.department_id:
                errors.append(StoreValidationError(change.department_id, "STORE_CODE_RESERVED", "门店编码已由其他部门保留"))
        if errors:
            raise InvalidStoreChanges(errors)
        return normalized

    @staticmethod
    def _lock_state(db: Session, expected_version: int, lock: bool) -> DatasetState:
        stmt = select(DatasetState).where(DatasetState.id == 1)
        state = db.scalar((stmt.with_for_update() if lock else stmt).execution_options(populate_existing=True))
        if state is None:
            raise RuntimeError("INITIALIZATION_INCOMPLETE")
        if state.data_version != expected_version:
            raise RuntimeError("DATASET_CHANGED")
        return state

    @staticmethod
    def _snapshot(profile: StoreProfile | None) -> dict:
        return {"is_store": bool(profile and profile.is_store), "store_code": profile.store_code if profile else None, "notes": profile.notes if profile else None}

    @staticmethod
    def _projection(db, overrides=None, *, current_read: bool = False):
        store_ids = set(db.scalars(StoreAdminService._read_statement(select(StoreProfile.department_id).where(StoreProfile.is_store.is_(True)), current_read)))
        for identifier, enabled in (overrides or {}).items():
            if enabled:
                store_ids.add(identifier)
            else:
                store_ids.discard(identifier)
        departments = {row.id: DomainDepartment(row.id, row.parent_id, row.id in store_ids, row.status, row.sync_quality) for row in db.scalars(StoreAdminService._read_statement(select(Department), current_read))}
        relations = list(db.scalars(StoreAdminService._read_statement(select(EmployeeDepartment), current_read)))
        by_employee: dict[str, list[Membership]] = {}
        for relation in relations:
            by_employee.setdefault(relation.employee_id, []).append(Membership(relation.employee_id, relation.department_id, relation.active))
        projection = {}
        for employee in db.scalars(StoreAdminService._read_statement(select(Employee), current_read)):
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
        projection = StoreAdminService._projection(db, current_read=True)
        db.execute(delete(EmployeeStore))
        for employee in db.scalars(StoreAdminService._read_statement(select(Employee), True)):
            result, paths = projection[employee.id]
            employee.primary_store_status = result.primary_store_status
            for store_id in result.store_ids:
                db.add(EmployeeStore(employee_id=employee.id, store_id=store_id, is_primary=store_id == result.primary_store_id, path=paths.get(store_id, [])))

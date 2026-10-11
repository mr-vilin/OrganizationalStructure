from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.services import ReadService
from app.public_api.cursor import CursorCodec, DatasetChanged, InvalidCursor
from app.web import utc_datetime

from .models import DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreProfile


class SqlReadService(ReadService):
    def __init__(self, sessions: sessionmaker[Session], cursor_secret: str):
        self._sessions = sessions
        self._cursors = CursorCodec(cursor_secret)

    def _state(self, db: Session) -> DatasetState:
        state = db.get(DatasetState, 1)
        if state is None or state.initialization_status != "complete":
            raise RuntimeError("INITIALIZATION_INCOMPLETE")
        return state

    @staticmethod
    def _meta(state: DatasetState, next_cursor: str | None = None) -> dict:
        return {
            "dataset_epoch": state.dataset_epoch,
            "data_version": state.data_version,
            "coverage_status": state.coverage_status,
            "last_full_sync_at": utc_datetime(state.last_full_sync_at),
            "next_cursor": next_cursor,
        }

    def status(self):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            return ({"initialization_status": state.initialization_status, "coverage_status": state.coverage_status}, self._meta(state))

    def list_departments(self, **filters):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            self._check_version(state, filters)
            stmt = select(Department).order_by(Department.id).limit(filters.get("limit", 100) + 1)
            if not filters.get("include_inactive"):
                stmt = stmt.where(Department.status == "active")
            if filters.get("parent_id") is not None:
                stmt = stmt.where(Department.parent_id == filters["parent_id"])
            if filters.get("root_id") is not None:
                if filters.get("include_descendants"):
                    tree = select(Department.id).where(Department.id == filters["root_id"]).cte("department_tree", recursive=True)
                    tree = tree.union_all(select(Department.id).join(tree, Department.parent_id == tree.c.id))
                    stmt = stmt.where(Department.id.in_(select(tree.c.id)))
                else:
                    stmt = stmt.where(Department.id == filters["root_id"])
            last_id = self._last_id(state, "departments", filters)
            if last_id:
                stmt = stmt.where(Department.id > last_id)
            rows = list(db.scalars(stmt))
            page, next_cursor = self._page(rows, filters.get("limit", 100))
            return ([self._department(db, row) for row in page], self._meta(state, self._next_cursor(state, "departments", filters, next_cursor)))

    def get_department(self, department_id: str):
        with self._sessions() as db, db.begin():
            state, row = self._state(db), db.get(Department, department_id)
            return (self._department(db, row) if row else None, self._meta(state))

    def list_employees(self, **filters):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            self._check_version(state, filters)
            stmt = select(Employee).distinct().order_by(Employee.id).limit(filters.get("limit", 100) + 1)
            if not filters.get("include_inactive"):
                stmt = stmt.where(Employee.status == "active")
            if filters.get("department_id"):
                department_ids = select(EmployeeDepartment.employee_id).where(EmployeeDepartment.active.is_(True))
                if filters.get("include_descendants"):
                    tree = select(Department.id).where(Department.id == filters["department_id"]).cte("employee_department_tree", recursive=True)
                    tree = tree.union_all(select(Department.id).join(tree, Department.parent_id == tree.c.id))
                    department_ids = department_ids.where(EmployeeDepartment.department_id.in_(select(tree.c.id)))
                else:
                    department_ids = department_ids.where(EmployeeDepartment.department_id == filters["department_id"])
                stmt = stmt.where(Employee.id.in_(department_ids))
            if filters.get("store_id"):
                stmt = stmt.where(Employee.id.in_(select(EmployeeStore.employee_id).where(EmployeeStore.store_id == filters["store_id"])))
            if filters.get("primary_store_id"):
                stmt = stmt.where(Employee.id.in_(select(EmployeeStore.employee_id).where(EmployeeStore.store_id == filters["primary_store_id"], EmployeeStore.is_primary.is_(True))))
            last_id = self._last_id(state, "employees", filters)
            if last_id:
                stmt = stmt.where(Employee.id > last_id)
            rows = list(db.scalars(stmt))
            page, next_cursor = self._page(rows, filters.get("limit", 100))
            return ([self._employee(db, row) for row in page], self._meta(state, self._next_cursor(state, "employees", filters, next_cursor)))

    def get_employee(self, employee_id: str):
        with self._sessions() as db, db.begin():
            state, row = self._state(db), db.get(Employee, employee_id)
            return (self._employee(db, row) if row else None, self._meta(state))

    def list_stores(self, **filters):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            self._check_version(state, filters)
            stmt = select(StoreProfile, Department).join(Department).where(StoreProfile.is_store.is_(True)).order_by(StoreProfile.department_id).limit(filters.get("limit", 100) + 1)
            if not filters.get("include_inactive"):
                stmt = stmt.where(Department.status == "active")
            last_id = self._last_id(state, "stores", filters)
            if last_id:
                stmt = stmt.where(StoreProfile.department_id > last_id)
            rows = list(db.execute(stmt))
            page, next_cursor = self._page(rows, filters.get("limit", 100), key=lambda row: row[0].department_id)
            return ([self._store(db, *row) for row in page], self._meta(state, self._next_cursor(state, "stores", filters, next_cursor)))

    def get_store(self, store_id: str):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            row = db.execute(select(StoreProfile, Department).join(Department).where(StoreProfile.department_id == store_id)).one_or_none()
            return (self._store(db, *row) if row else None, self._meta(state))

    def list_store_employees(self, store_id: str, **filters):
        filters["store_id"] = store_id
        if filters.pop("membership", "all") == "primary":
            filters["primary_store_id"] = store_id
            filters.pop("store_id")
        return self.list_employees(**filters)

    @staticmethod
    def _check_version(state: DatasetState, filters: dict) -> None:
        if filters.get("dataset_epoch") not in (None, state.dataset_epoch) or filters.get("data_version") not in (None, state.data_version):
            raise RuntimeError("DATASET_CHANGED")

    @staticmethod
    def _bound_filters(resource: str, filters: dict) -> dict:
        return {"resource": resource, **{key: value for key, value in filters.items() if key not in {"cursor", "dataset_epoch", "data_version"}}}

    def _last_id(self, state: DatasetState, resource: str, filters: dict) -> str | None:
        cursor = filters.get("cursor")
        if not cursor:
            return None
        try:
            return self._cursors.decode(cursor, epoch=state.dataset_epoch, version=state.data_version, filters=self._bound_filters(resource, filters)).last_id
        except DatasetChanged as exc:
            raise RuntimeError("DATASET_CHANGED") from exc
        except InvalidCursor as exc:
            raise RuntimeError("INVALID_CURSOR") from exc

    def _next_cursor(self, state: DatasetState, resource: str, filters: dict, last_id: str | None) -> str | None:
        if last_id is None:
            return None
        return self._cursors.encode(epoch=state.dataset_epoch, version=state.data_version, filters=self._bound_filters(resource, filters), last_id=last_id)

    @staticmethod
    def _page(rows: list, limit: int, key=lambda row: row.id):
        has_more = len(rows) > limit
        page = rows[:limit]
        return page, key(page[-1]) if has_more and page else None

    @staticmethod
    def _department(db: Session, row: Department) -> dict:
        profile = db.get(StoreProfile, row.id)
        names, current, visited = [], row, set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            names.append(current.name)
            current = db.get(Department, current.parent_id) if current.parent_id else None
        leader = db.get(Employee, row.leader_user_id) if row.leader_user_id else None
        return {"id": row.id, "parent_id": row.parent_id, "name": row.name, "path": list(reversed(names)), "status": row.status, "sync_quality": row.sync_quality, "is_virtual_root": row.is_virtual_root, "leader_user_id": row.leader_user_id, "leader_name": leader.name if leader else None, "is_store": bool(profile and profile.is_store), "store_code": profile.store_code if profile else None, "notes": profile.notes if profile else None}

    @staticmethod
    def _store(db: Session, profile: StoreProfile, department: Department) -> dict:
        names, current, visited = [], department, set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            names.append(current.name)
            current = db.get(Department, current.parent_id) if current.parent_id else None
        employee_count = db.scalar(select(func.count(func.distinct(EmployeeStore.employee_id))).where(EmployeeStore.store_id == department.id)) or 0
        primary_count = db.scalar(select(func.count(func.distinct(EmployeeStore.employee_id))).where(EmployeeStore.store_id == department.id, EmployeeStore.is_primary.is_(True))) or 0
        return {"id": department.id, "department_id": department.id, "name": department.name, "path": list(reversed(names)), "status": department.status, "is_store": profile.is_store, "store_code": profile.store_code, "notes": profile.notes, "employee_count": employee_count, "primary_employee_count": primary_count}

    @staticmethod
    def _employee(db: Session, row: Employee) -> dict:
        memberships = list(db.scalars(select(EmployeeDepartment.department_id).where(EmployeeDepartment.employee_id == row.id, EmployeeDepartment.active.is_(True))))
        stores = list(db.execute(select(EmployeeStore.store_id, EmployeeStore.is_primary).where(EmployeeStore.employee_id == row.id)))
        primary_store = next((store_id for store_id, primary in stores if primary), None)
        department_details = [SqlReadService._department(db, db.get(Department, identifier)) for identifier in memberships]
        store_details = []
        for relation in db.scalars(select(EmployeeStore).where(EmployeeStore.employee_id==row.id)):
            department=db.get(Department,relation.store_id)
            store_details.append({'id':relation.store_id,'name':department.name,'is_primary':relation.is_primary,'path':relation.path,'path_names':[db.get(Department,identifier).name for identifier in relation.path]})
        leader = db.get(Employee, row.leader_user_id) if row.leader_user_id else None
        return {"id": row.id, "name": row.name, "employee_no": row.employee_no, "status": row.status, "sync_quality": row.sync_quality, "employee_type_id": row.employee_type_id, "employee_type_name": row.employee_type_name, "job_title": row.job_title, "leader_user_id": row.leader_user_id, "leader_name": leader.name if leader else None, "permission_role_id": row.permission_role_id, "permission_role_name": row.permission_role_name, "store_attribute_id": row.store_attribute_id, "store_attribute_name": row.store_attribute_name, "department_ids": memberships, "departments":department_details,"stores":store_details,"primary_department_id": row.primary_department_id, "store_ids": [item[0] for item in stores], "primary_store_id": primary_store, "primary_store_status": row.primary_store_status}

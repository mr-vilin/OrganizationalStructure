from dataclasses import dataclass, replace


UNSET = object()


@dataclass(frozen=True)
class StorePatch:
    department_id: str
    is_store: bool
    store_code: str | None | object = UNSET
    notes: str | None | object = UNSET


@dataclass(frozen=True)
class StoreValidationError:
    department_id: str
    code: str
    message: str


class InvalidStoreChanges(ValueError):
    def __init__(self, errors: list[StoreValidationError]):
        self.errors = errors
        super().__init__("invalid store changes")


def validate_store_changes(changes: list[StorePatch], *, departments: dict[str, dict], raise_errors: bool = True):
    normalized: list[StorePatch] = []
    errors: list[StoreValidationError] = []
    seen_codes: set[str] = set()
    for change in changes:
        department = departments.get(change.department_id)
        code = change.store_code
        if code is not UNSET:
            code = code.strip() if code and code.strip() else None
        item = replace(change, store_code=code)
        if department is None:
            errors.append(StoreValidationError(change.department_id, "DEPARTMENT_NOT_FOUND", "部门不存在"))
        elif change.is_store and department["is_virtual_root"]:
            errors.append(StoreValidationError(change.department_id, "VIRTUAL_ROOT", "虚拟根不能设为门店"))
        elif change.is_store and department["status"] != "active":
            errors.append(StoreValidationError(change.department_id, "DEPARTMENT_INACTIVE", "失效部门不能新设为门店"))
        elif code is not UNSET and code is not None and code in seen_codes:
            errors.append(StoreValidationError(change.department_id, "DUPLICATE_STORE_CODE", "批次内门店编码重复"))
        else:
            if code is not UNSET and code is not None:
                seen_codes.add(code)
            normalized.append(item)
    if errors and raise_errors:
        raise InvalidStoreChanges(errors)
    return errors if errors else normalized


def merge_store_patch(current: dict, patch: StorePatch) -> dict:
    if not patch.is_store:
        return {**current, "is_store": False}
    return {
        "is_store": True,
        "store_code": current.get("store_code") if patch.store_code is UNSET else patch.store_code,
        "notes": current.get("notes") if patch.notes is UNSET else patch.notes,
    }

from typing import Final

# Central source of truth for contract project types.
# Future: replace the hardcoded dict with values loaded from a settings table.
PROJECT_TYPE_MAP: Final[dict[str, str]] = {
    "WEB_APP": "WBA",
    "MOBILE_APP": "MBA",
    "ML_PROJECT": "MLA",
    "DATA_PIPELINE": "DPL",
    "OTHER": "OTH",
}

# Backward-compatible alias for existing imports.
PROJECT_TYPE_TO_CODE: Final[dict[str, str]] = PROJECT_TYPE_MAP

# Human-readable contract code prefix for the tenant/company.
# Future: source from dynamic settings per owner.
CONTRACT_CODE_COMPANY: Final[str] = "SRE"


def get_allowed_project_types() -> tuple[str, ...]:
    """Returns all currently supported project types."""
    return tuple(PROJECT_TYPE_MAP.keys())


def is_valid_project_type(project_type: str) -> bool:
    return project_type in PROJECT_TYPE_MAP


def get_project_type_code(project_type: str) -> str:
    """
    Returns the short code prefix for contract code generation.
    Raises ValueError for unknown project types.
    """
    try:
        return PROJECT_TYPE_MAP[project_type]
    except KeyError as exc:
        allowed = ", ".join(get_allowed_project_types())
        raise ValueError(
            f"Invalid project_type '{project_type}'. Allowed values: {allowed}."
        ) from exc


def get_company_code() -> str:
    return CONTRACT_CODE_COMPANY

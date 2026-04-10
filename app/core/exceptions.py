# app/core/exceptions.py


class ContractBaseError(Exception):
    """
    Base for all contract domain errors.
    Subclasses carry .message so route handlers can pass it
    directly to HTTPException(detail=...) without reformatting.
    """
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ContractValidationError(ContractBaseError):
    """Business rule violated. Maps to HTTP 400."""
    pass


class CounterpartyNotFoundError(ContractBaseError):
    """Referenced counterparty missing for this owner. Maps to HTTP 404."""
    pass


class ContractNotFoundError(ContractBaseError):
    """Contract row missing for this owner. Maps to HTTP 404."""
    pass


class DuplicateContractError(ContractBaseError):
    """Same (owner_id, counterparty_id, start_date) already exists. Maps to HTTP 409."""
    pass


class DuplicateCounterpartyError(ContractBaseError):
    """
    Counterparty uniqueness constraint fired and recovery failed.
    Maps to HTTP 409.
    """
    pass
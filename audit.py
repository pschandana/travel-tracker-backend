from datetime import datetime
from models import db, AuditLog


def write_audit(operation, table_name, record_id, user_id=None, autocommit=True):
    """Create an AuditLog entry for a create, update, or delete operation.

    Args:
        operation (str): "CREATE", "UPDATE", or "DELETE"
        table_name (str): Name of the affected table (e.g. "trip", "user")
        record_id (int): Primary key of the affected record
        user_id (int, optional): ID of the user who performed the operation
        autocommit (bool): If False, caller is responsible for committing the session
    """
    entry = AuditLog(
        operation=operation,
        table_name=table_name,
        record_id=record_id,
        user_id=user_id,
        timestamp=datetime.utcnow(),
    )
    db.session.add(entry)
    if autocommit:
        db.session.commit()

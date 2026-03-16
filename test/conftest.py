import pytest
from app.database.session import SessionLoacal
from sqlalchemy import event

@pytest.fixture(scope="function")
def db():
    # Use connection from engine directly
    connection = SessionLoacal().get_bind().connect()
    
    # Start a nested transaction (SAVEPOINT)
    transaction = connection.begin_nested()

    # Bind the session to the connection
    session = SessionLoacal(bind=connection)

    # Ensure SAVEPOINTs are restarted after each flush
    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess, trans):
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.rollback()
        connection.close()
        session.close()

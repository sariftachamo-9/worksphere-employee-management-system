from app import create_app
from extensions import db
from database.models import LeaveRequest

app = create_app()
with app.app_context():
    count = LeaveRequest.query.delete()
    db.session.commit()
    print(f"Deleted {count} leave requests.")


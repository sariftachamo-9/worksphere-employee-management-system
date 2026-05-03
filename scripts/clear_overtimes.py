from app import create_app
from extensions import db
from database.models import OvertimeRequest

app = create_app()
with app.app_context():
    count = OvertimeRequest.query.delete()
    db.session.commit()
    print(f"Deleted {count} overtime requests.")


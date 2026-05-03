from app import create_app
from extensions import db
from database.models import EmployeeProfile

app = create_app('development')
with app.app_context():
    jenik = EmployeeProfile.query.filter_by(full_name='Jenik Shrestha').first()
    if jenik:
        jenik.workshop_status = 'Ongoing'
        jenik.user.is_active = True
        db.session.commit()
        print("Restored Jenik to Active/Ongoing")

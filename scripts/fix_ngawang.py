from app import create_app
from extensions import db
from database.models import User, EmployeeProfile
from werkzeug.security import generate_password_hash
from datetime import datetime

app = create_app('development')
with app.app_context():
    # 2. Recreate the CORRECT Ngawang
    correct_email = 'em-it-ngawang@ems.com'
    existing = User.query.filter_by(email=correct_email).first()
    if not existing:
        print("Recreating CORRECT Ngawang...")
        new_user = User(
            email=correct_email,
            password_hash=generate_password_hash('password123'),
            role='employee',
            is_active=True
        )
        db.session.add(new_user)
        db.session.flush() # get user ID
        
        new_profile = EmployeeProfile(
            user_id=new_user.id,
            employee_id='EM-IT-003',
            full_name='Ngawang Sherpa',
            phone='+977 9813008845',
            personal_email='ngawangsherpa792@gmail.com',
            department='IT',
            designation='Cyber Security Expert',
            joining_date=datetime.strptime('2026-03-16', '%Y-%m-%d').date(),
            base_salary=120000.0,
            workshop_status='Ongoing'
        )
        db.session.add(new_profile)
        print("Restored correct Ngawang!")
    else:
        print("Correct Ngawang already exists.")

    db.session.commit()
    print("Database committed.")

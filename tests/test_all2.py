import sys
from app import create_app
from extensions import db
from database.models import User
import traceback

app = create_app('development')
endpoints = [
    '/admin/employees',
    '/admin/interns',
    '/admin/students',
    '/admin/remove-staff',
    '/admin/remove-staff?role=intern',
    '/admin/remove-staff?role=student',
    '/admin/dashboard'
]

with app.test_client() as client:
    with app.app_context():
        user = User.query.filter_by(role='admin').first()
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['session_version'] = app.config.get('BOOT_ID')
        
    for ep in endpoints:
        response = client.get(ep)
        if response.status_code == 500:
            print(f"FAILED 500: {ep}")
            print(response.get_data(as_text=True))
        else:
            print(f"SUCCESS {response.status_code}: {ep}")

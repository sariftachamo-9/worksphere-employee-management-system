import sys
from app import create_app
from extensions import db
from database.models import User
from flask_login import login_user
import traceback

app = create_app('development')
with app.test_request_context('/'):
    user = User.query.filter_by(role='admin').first()

endpoints = [
    '/admin/employees',
    '/admin/interns',
    '/admin/students',
    '/admin/remove-staff',
    '/admin/remove-staff?role=intern',
    '/admin/remove-staff?role=student',
    '/admin/remove-staff?search=None',
    '/admin/dashboard'
]

for ep in endpoints:
    with app.test_client() as client:
        with client.session_transaction() as sess:
            # log in admin
            pass
        
        # Or just test using request context
        pass

for ep in endpoints:
    with app.test_request_context(ep):
        try:
            user = User.query.filter_by(role='admin').first()
            login_user(user)
            # Find the view function
            rule = app.url_map.bind('').match(ep)
            view_func = app.view_functions[rule[0]]
            res = view_func(**rule[1])
            print(f"SUCCESS {ep}")
        except Exception as e:
            print(f"FAILED {ep}: {e}")
            traceback.print_exc()

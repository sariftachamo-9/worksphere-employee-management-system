import sys
from app import create_app
from extensions import db
from database.models import User, EmployeeProfile

app = create_app('development')
with app.app_context():
    interns = User.query.filter_by(role='intern').all()
    print(f"Total interns: {len(interns)}")
    for i in interns:
        profile = i.profile
        name = profile.full_name if profile else 'No profile'
        print(f"ID: {i.id}, Email: {i.email}, Name: {name}, Active: {i.is_active}")
        
    students = User.query.filter_by(role='student').all()
    print(f"Total students: {len(students)}")
    for i in students:
        profile = i.profile
        name = profile.full_name if profile else 'No profile'
        print(f"ID: {i.id}, Email: {i.email}, Name: {name}, Active: {i.is_active}")

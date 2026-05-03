import sys
from app import create_app
from extensions import db
from database.models import User, EmployeeProfile
from flask import render_template
import datetime

app = create_app('development')
with app.test_request_context('/admin/interns'):
    try:
        users = User.query.join(EmployeeProfile).filter(User.role == 'intern').all()
        depts = db.session.query(EmployeeProfile.department).distinct().filter(EmployeeProfile.department != None).all()
        desigs = db.session.query(EmployeeProfile.designation).distinct().filter(EmployeeProfile.designation != None).all()
        
        render_template('admin/staff_directory.html', 
                       users=users, 
                       title="Interns List", 
                       admin_title="Intern Management",
                       add_label="Add Intern",
                       add_endpoint="admin.add_intern",
                       depts=[d[0] for d in depts],
                       desigs=[d[0] for d in desigs],
                       curr_dept='',
                       curr_desig='',
                       curr_search='',
                       now=datetime.datetime.now())
        print("SUCCESS")
    except Exception as e:
        import traceback
        traceback.print_exc()

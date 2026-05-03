from app import create_app
from extensions import db
from database.models import User, EmployeeProfile, Attendance, TimeLog, LeaveRequest, Payroll, ContactQuery, Notice, OvertimeRequest, Expense, Revenue, LoginLog, LoginToken

app = create_app('development')
with app.app_context():
    uid = 24
    wrong_user = User.query.get(uid)
    if wrong_user:
        print(f"Deleting WRONG Ngawang: User ID {uid}")
        
        # Delete related child records manually
        Attendance.query.filter_by(user_id=uid).delete()
        TimeLog.query.filter_by(user_id=uid).delete()
        LeaveRequest.query.filter_by(user_id=uid).delete()
        Payroll.query.filter_by(user_id=uid).delete()
        ContactQuery.query.filter_by(user_id=uid).delete()
        Notice.query.filter_by(target_user_id=uid).delete()
        OvertimeRequest.query.filter_by(user_id=uid).delete()
        Expense.query.filter_by(user_id=uid).delete()
        Revenue.query.filter_by(user_id=uid).delete()
        LoginLog.query.filter_by(user_id=uid).delete()
        LoginToken.query.filter_by(user_id=uid).delete()
        
        profile = EmployeeProfile.query.filter_by(user_id=uid).first()
        if profile:
            db.session.delete(profile)
        db.session.delete(wrong_user)
        print("Deleted wrong Ngawang.")
        db.session.commit()
        print("Database committed successfully!")
    else:
        print("User 24 not found!")

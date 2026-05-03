from app import create_app
from extensions import db
from database.models import (User, EmployeeProfile, Attendance, TimeLog, LeaveRequest, Payroll, AuditLog, ContactQuery, 
                             Notice, OvertimeRequest, Expense, Revenue, LoginLog, LoginToken, PayrollRun)

app = create_app('development')
with app.app_context():
    # Clear all Audit Logs first as requested
    AuditLog.query.delete()
    print("Cleared all Audit Logs.")

    # Find Ngawang
    profile = EmployeeProfile.query.filter(EmployeeProfile.full_name.ilike('%Ngawang Sherpa%')).first()
    if profile:
        user = profile.user
        uid = user.id
        print(f"Found Ngawang: User ID {uid}")
        
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
        
        # Nullify fields where he is approver
        OvertimeRequest.query.filter_by(approved_by=uid).update({'approved_by': None})
        PayrollRun.query.filter_by(processed_by=uid).update({'processed_by': None})
        
        # Delete Profile and User
        db.session.delete(profile)
        db.session.delete(user)
        print("Successfully wiped Ngawang Sherpa from the system.")
    else:
        print("Ngawang not found!")

    db.session.commit()
    print("Database committed successfully.")

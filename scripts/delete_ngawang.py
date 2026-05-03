from app import create_app
from extensions import db
from database.models import User, EmployeeProfile, LeaveRequest, Attendance, AuditLog, ContactQuery

app = create_app('development')
with app.app_context():
    # Find Ngawang
    profile = EmployeeProfile.query.filter(EmployeeProfile.full_name.ilike('%Ngawang Sherpa%')).first()
    if profile:
        user = profile.user
        print(f"Found Ngawang: User ID {user.id}")
        
        # Delete related records
        LeaveRequest.query.filter_by(user_id=user.id).delete()
        Attendance.query.filter_by(user_id=user.id).delete()
        ContactQuery.query.filter_by(user_id=user.id).delete()
        AuditLog.query.filter_by(user_id=user.id).delete()
        
        # Delete Profile and User
        db.session.delete(profile)
        db.session.delete(user)
        print("Deleted Ngawang successfully.")
    else:
        print("Ngawang not found!")
        
    # Clear all Recent Activity (AuditLog)
    deleted_logs = AuditLog.query.delete()
    print(f"Cleared {deleted_logs} Audit Log records.")
    
    db.session.commit()
    print("Database committed successfully.")

from app import create_app
from extensions import db
from database.models import User, EmployeeProfile, Payroll
from utils.payroll_service import PayrollService

app = create_app()
with app.app_context():
    users = User.query.filter_by(role='intern').all()
    for u in users:
        p = u.profile
        if p and p.base_salary == 0.0:
            # Let's find their 2026-04 payroll to get their base salary
            p4 = Payroll.query.filter_by(user_id=u.id, year=2026, month=4).first()
            if p4:
                print(f"Fixing User {u.username}: old base_salary was {p4.snapshot_base_salary}")
                p.base_salary = p4.snapshot_base_salary
                db.session.commit()
                # Run payroll generation for them
                PayrollService.upsert_payroll_for_user(u, 5, 2026)
                db.session.commit()
                print(f"Generated 2026-05 payroll for {u.username}")


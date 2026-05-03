from app import create_app
from extensions import db
from database.models import User, EmployeeProfile, Payroll
app = create_app()
with app.app_context():
    users = User.query.filter_by(role='intern').all()
    print("INTERNS:")
    for u in users:
        p = u.profile
        print(f"User {u.username}: Profile={'Yes' if p else 'No'}, base_salary={p.base_salary if p else 'N/A'}")
        p4 = Payroll.query.filter_by(user_id=u.id, year=2026, month=4).first()
        p5 = Payroll.query.filter_by(user_id=u.id, year=2026, month=5).first()
        print(f"  - 2026-04 Payroll: {'Yes' if p4 else 'No'}, gross={p4.gross_pay if p4 else 'N/A'}")
        print(f"  - 2026-05 Payroll: {'Yes' if p5 else 'No'}, gross={p5.gross_pay if p5 else 'N/A'}")


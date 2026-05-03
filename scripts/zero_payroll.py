from app import create_app
from extensions import db
from database.models import Payroll

app = create_app('development')
with app.app_context():
    payrolls = Payroll.query.all()
    for p in payrolls:
        p.absent_days = 0.0
        p.leave_days = 0.0
        p.absent_deduction = 0.0
        p.leave_deduction = 0.0
        p.lop_deduction = 0.0
        # Recalculate net_pay since deductions are gone
        p.net_pay = p.gross_pay
        p.net_month_earning = p.gross_pay
    db.session.commit()
    print("All past and present payroll absent/leave days zeroed out!")

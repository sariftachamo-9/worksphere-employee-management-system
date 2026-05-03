from app import create_app
from database.models import Payroll
from sqlalchemy import func
app = create_app('development')
with app.app_context():
    history_query = Payroll.query.with_entities(
        Payroll.year,
        Payroll.month,
        func.count(Payroll.id).label('total_count'),
        func.sum(func.case((Payroll.payment_status == 'Paid', 1), else_=0)).label('paid_count')
    ).group_by(Payroll.year, Payroll.month).all()
    
    for row in history_query:
        print(f"{row.year}-{row.month}: Total {row.total_count}, Paid {row.paid_count}")

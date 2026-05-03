from app import create_app
from extensions import db
from database.models import User, EmployeeProfile, Revenue
from utils.time_utils import get_nepal_time
from utils.financial_service import FinancialService

app = create_app('development')
with app.app_context():
    today = get_nepal_time()
    month = today.month
    year = today.year
    
    # 1. Clear old Revenue data
    Revenue.query.delete()
    db.session.commit()
    
    # 2. Re-create Revenue entries for active students
    students = User.query.join(EmployeeProfile).filter(
        User.role == 'student',
        User.is_active.is_(True),
        EmployeeProfile.base_salary > 0
    ).all()

    for student in students:
        FinancialService.create_revenue_entry(student.id, month, year)
    
    # 3. Generate summary
    FinancialService.generate_financial_summary(month, year)
    
    print(f"Created revenue entries for {len(students)} students.")

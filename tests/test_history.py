from app import create_app
from utils.payroll_service import PayrollService

app = create_app('development')
with app.app_context():
    analytics = PayrollService.get_dashboard_analytics()
    for item in analytics.get('history_data', []):
        print(item)

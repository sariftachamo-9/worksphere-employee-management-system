from app import create_app
from utils.payroll_service import PayrollService

app = create_app('development')
with app.app_context():
    print("Recalculating payrolls...")
    PayrollService.process_payroll_cycle(triggered_by='system_fix')
    PayrollService.sync_payroll_totals()
    PayrollService.backfill_net_month_earning()
    print("Done!")

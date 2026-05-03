#!/usr/bin/env python3
"""
Reset all payroll payment statuses to 'Unpaid' and clear paid dates.
Run this script to reset all payroll records to unpaid status.
"""

import sys
import os
# Add the parent directory to the path so we can import from the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from database.models import Payroll
from app import create_app

def reset_payroll_statuses():
    app = create_app()
    with app.app_context():
        try:
            # Update all payroll records to set payment_status to 'Unpaid' and paid_date to None
            updated_count = db.session.query(Payroll).update({
                'payment_status': 'Unpaid',
                'paid_date': None
            })
            db.session.commit()
            print(f"Successfully reset {updated_count} payroll records to 'Unpaid' status.")
        except Exception as e:
            db.session.rollback()
            print(f"Error resetting payroll statuses: {e}")

if __name__ == "__main__":
    reset_payroll_statuses()
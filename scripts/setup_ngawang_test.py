#!/usr/bin/env python3
"""
Setup ngawang sherpa test employee with 3 days leave for payroll deduction demo
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from database.models import User, EmployeeProfile, LeaveRequest, Payroll
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

def setup_ngawang():
    app = create_app()
    with app.app_context():
        print("Setting up ngawang sherpa test employee...")
        
        # Check if exists
        user = User.query.filter_by(email='ngawang.sherpa@ems.com').first()
        if user:
            print(f"✓ Employee already exists: {user.profile.full_name}")
            print(f"  Employee ID: {user.profile.employee_id}")
        else:
            # Create user
            user = User(
                email='ngawang.sherpa@ems.com',
                password_hash=generate_password_hash('NgawangTest@123', method='pbkdf2:sha256'),
                role='employee',
                is_active=True
            )
            db.session.add(user)
            db.session.flush()
            
            # Create profile
            profile = EmployeeProfile(
                user_id=user.id,
                full_name='ngawang sherpa',
                employee_id='EMP-001',
                department='Operations',
                designation='Staff',
                joining_date=datetime(2023, 1, 1).date(),
                base_salary=10000.0,
                hra=500.0,
                transport_allowance=200.0,
                overtime_rate=100.0
            )
            db.session.add(profile)
            db.session.commit()
            print(f"✓ Created employee: {profile.full_name}")
            print(f"  Employee ID: {profile.employee_id}")
            print(f"  Base Salary: Rs. {profile.base_salary}")
            print(f"  HRA: Rs. {profile.hra}")
            print(f"  Transport: Rs. {profile.transport_allowance}")
        
        # Create 3-day leave for current month
        leave_exists = LeaveRequest.query.filter_by(
            user_id=user.id,
            start_date=datetime(2026, 5, 5).date(),
            end_date=datetime(2026, 5, 7).date()
        ).first()
        
        if leave_exists:
            print(f"✓ Leave already exists: {leave_exists.start_date} to {leave_exists.end_date}")
        else:
            leave = LeaveRequest(
                user_id=user.id,
                leave_type='casual',
                start_date=datetime(2026, 5, 5).date(),
                end_date=datetime(2026, 5, 7).date(),
                reason='Test leave for deduction demonstration',
                status='approved'
            )
            db.session.add(leave)
            db.session.commit()
            print(f"✓ Created 3-day leave: May 5-7, 2026 (APPROVED)")
        
        # Create payroll for current month
        payroll = Payroll.query.filter_by(
            user_id=user.id,
            month=5,
            year=2026
        ).first()
        
        if payroll:
            print(f"✓ Payroll already exists for May 2026")
        else:
            payroll = Payroll(
                user_id=user.id,
                month=5,
                year=2026,
                snapshot_base_salary=120000.0,  # Annual
                snapshot_hra=500.0,
                snapshot_transport=200.0,
                status='generated'
            )
            db.session.add(payroll)
            db.session.commit()
            print(f"✓ Created payroll for May 2026")
        
        print("\n" + "="*60)
        print("EXPECTED PAYROLL OUTPUT:")
        print("="*60)
        print(f"Monthly Base Salary:      Rs. 10,000.00")
        print(f"HRA:                      Rs.    500.00")
        print(f"Transport/Auto:           Rs.    200.00")
        print(f"─────────────────────────────────────────")
        print(f"Total Components:         Rs. 10,700.00")
        print(f"\nDeduction Calculation:")
        print(f"  Daily Rate: 10,000 ÷ 22 = Rs. 454.55")
        print(f"  Leave Days: 3 days (May 5-7)")
        print(f"  Deduction: 3 × 454.55 = Rs. 1,363.65")
        print(f"\nFinal Net Monthly Salary:")
        print(f"  10,700 - 1,363.65 = Rs. 9,336.35")
        print("="*60)

if __name__ == '__main__':
    setup_ngawang()

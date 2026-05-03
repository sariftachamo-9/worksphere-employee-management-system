#!/usr/bin/env python3
"""
Script to delete all payroll history and generate fresh payroll data for April 5th, 2026
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from database.models import User, Payroll, EmployeeProfile
from datetime import datetime

app = create_app('development')

def regenerate_payroll():
    with app.app_context():
        try:
            print("=" * 60)
            print("PAYROLL REGENERATION SCRIPT - April 5, 2026")
            print("=" * 60)
            
            # Step 1: Delete all existing payroll records
            print("\n[1/3] Deleting all existing payroll records...")
            deleted_count = Payroll.query.delete()
            db.session.commit()
            print(f"✓ Deleted {deleted_count} payroll records")
            
            # Step 2: Get all employees and interns
            print("\n[2/3] Fetching all employees and interns...")
            employees = User.query.filter(
                User.role.in_(['employee', 'intern']),
                User.is_active == True
            ).all()
            print(f"✓ Found {len(employees)} active employees/interns")
            
            if len(employees) == 0:
                print("! No employees found. Cannot generate payroll.")
                return False
            
            # Step 3: Generate payroll for April 2026
            print("\n[3/3] Generating payroll data for April 2026...")
            
            payroll_records = []
            april_year = 2026
            april_month = 4
            
            for emp in employees:
                profile = emp.profile
                if not profile:
                    print(f"⚠ Skipping user {emp.id} - no profile found")
                    continue
                
                # Calculate salary components
                base_salary = profile.base_salary or 30000
                hra = profile.hra or (base_salary * 0.1)  # 10% of base
                transport = profile.transport_allowance or (base_salary * 0.05)  # 5% of base
                
                gross_pay = base_salary + hra + transport
                
                # Calculate deductions (realistic percentages)
                tax_deduction = profile.tax_deduction or (gross_pay * 0.05)  # 5% tax
                insurance_deduction = profile.insurance_deduction or (gross_pay * 0.02)  # 2% insurance
                other_deductions = profile.other_deductions or 0
                
                total_deductions = tax_deduction + insurance_deduction + other_deductions
                net_pay = gross_pay - total_deductions
                
                # Create payroll record
                payroll = Payroll(
                    user_id=emp.id,
                    month=april_month,
                    year=april_year,
                    snapshot_base_salary=base_salary,
                    snapshot_hra=hra,
                    snapshot_transport=transport,
                    overtime_earnings=0.0,
                    lop_deduction=0.0,
                    gross_pay=gross_pay,
                    net_pay=net_pay,
                    status='paid',
                    generated_on=datetime(2026, 4, 5),
                    processed_date=datetime(2026, 4, 5),
                    cycle_label='APR-2026'
                )
                payroll_records.append(payroll)
            
            # Batch insert all records
            db.session.bulk_save_objects(payroll_records)
            db.session.commit()
            print(f"✓ Generated {len(payroll_records)} payroll records")
            
            # Step 4: Display summary
            print("\n" + "=" * 60)
            print("PAYROLL SUMMARY FOR APRIL 2026")
            print("=" * 60)
            
            total_gross = sum(p.gross_pay for p in payroll_records)
            total_net = sum(p.net_pay for p in payroll_records)
            
            print(f"\nTotal Employees: {len(payroll_records)}")
            print(f"Total Gross Salary: Rs. {total_gross:,.2f}")
            print(f"Total Net Salary:  Rs. {total_net:,.2f}")
            print(f"Total Deductions:  Rs. {(total_gross - total_net):,.2f}")
            
            print("\n" + "=" * 60)
            print("✓ PAYROLL REGENERATION COMPLETED SUCCESSFULLY")
            print("=" * 60)
            
            return True
            
        except Exception as e:
            print(f"\n✗ ERROR: {str(e)}")
            db.session.rollback()
            import traceback
            traceback.print_exc()
            return False

if __name__ == '__main__':
    success = regenerate_payroll()
    sys.exit(0 if success else 1)

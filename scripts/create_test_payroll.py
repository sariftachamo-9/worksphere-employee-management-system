#!/usr/bin/env python3
"""
Test Payroll Creation Script - ngawang sherpa Example
Demonstrates deduction calculation for 3 days leave
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from database.models import User, EmployeeProfile, LeaveRequest
from utils.time_utils import get_nepal_time
from datetime import datetime, timedelta

def create_test_employee():
    """Create ngawang sherpa employee for testing"""
    with app.app_context():
        # Check if employee exists
        existing = User.query.filter_by(email='ngawang.sherpa@ems.com').first()
        if existing:
            print("✓ ngawang sherpa already exists")
            return existing
        
        # Create new user
        user = User(
            email='ngawang.sherpa@ems.com',
            role='employee',
            is_active=True
        )
        user.set_password('NgawangTest@123')
        
        db.session.add(user)
        db.session.flush()
        
        # Create employee profile
        profile = EmployeeProfile(
            user_id=user.id,
            full_name='ngawang sherpa',
            employee_id='EMP-NGAWANG-001',
            base_salary=10000,  # Rs. 10,000 monthly
            hra=500,  # HRA if applicable
            transport_allowance=200,  # Auto/Transport
            overtime_rate=100,  # Per hour
            phone_number='+977-9800000001'
        )
        
        db.session.add(profile)
        db.session.commit()
        
        print(f"✓ Created employee: {profile.full_name} (ID: {profile.employee_id})")
        print(f"  - Monthly Salary: Rs. {profile.base_salary}")
        print(f"  - HRA: Rs. {profile.hra}")
        print(f"  - Transport: Rs. {profile.transport_allowance}")
        
        return user


def create_test_leave():
    """Create 3 days of leave for ngawang sherpa"""
    with app.app_context():
        user = User.query.filter_by(email='ngawang.sherpa@ems.com').first()
        if not user:
            print("✗ Employee not found. Create employee first.")
            return
        
        # Current month dates
        today = get_nepal_time().date()
        start_date = today.replace(day=1)
        
        # Create 3-day leave starting from 5th of month
        leave_start = start_date.replace(day=5)
        leave_end = leave_start + timedelta(days=2)  # 3 days (5, 6, 7)
        
        # Check if leave already exists
        existing = LeaveRequest.query.filter_by(
            user_id=user.id,
            start_date=leave_start
        ).first()
        
        if existing:
            print("✓ Leave record already exists")
            return
        
        # Create leave request (approved)
        leave = LeaveRequest(
            user_id=user.id,
            leave_type='casual',
            start_date=leave_start,
            end_date=leave_end,
            reason='Test leave for deduction calculation',
            status='approved',
            approved_by=1  # Assuming admin user ID = 1
        )
        
        db.session.add(leave)
        db.session.commit()
        
        print(f"✓ Created approved leave for {user.profile.full_name}")
        print(f"  - Leave Period: {leave_start} to {leave_end} (3 days)")
        print(f"  - Status: {leave.status}")


def show_calculation():
    """Display deduction calculation example"""
    print("\n" + "="*60)
    print("PAYROLL DEDUCTION CALCULATION EXAMPLE")
    print("="*60)
    print("\nEmployee: ngawang sherpa")
    print("Monthly Salary (Base): Rs. 10,000")
    print("\nCalculation Steps:")
    print("─" * 60)
    print("1. Working Days in Month: 22 (Mon-Fri)")
    daily_rate = 10000 / 22
    print(f"   Daily Rate = 10,000 ÷ 22 = Rs. {daily_rate:.2f}")
    
    print("\n2. Leave Days Deduction:")
    print("   If 3 days APPROVED LEAVE → No deduction (paid leave)")
    print("   If 3 days UNAPPROVED/ABSENT → Deduction = 3 × Rs. {:.2f}".format(daily_rate))
    deduction = 3 * daily_rate
    print(f"                           = Rs. {deduction:.2f}")
    
    print("\n3. Monthly Components:")
    print("   Base Salary:    Rs. 10,000.00")
    print("   HRA:            Rs.    500.00 (if provided)")
    print("   Transport:      Rs.    200.00 (if provided)")
    print("   OT Earnings:    Rs.      0.00 (if worked)")
    subtotal = 10000 + 500 + 200
    print(f"   Subtotal:       Rs. {subtotal:>10.2f}")
    
    print("\n4. Final Net Monthly Salary:")
    print(f"   Subtotal:       Rs. {subtotal:>10.2f}")
    print(f"   - Deduction:    Rs. {deduction:>10.2f}")
    net = subtotal - deduction
    print("   " + "─" * 30)
    print(f"   Net Monthly:    Rs. {net:>10.2f}")
    
    print("\n" + "="*60)
    print("EXPECTED PAYROLL MANAGE DISPLAY:")
    print("─" * 60)
    print(f"{'ngawang sherpa':<30} | Deduction: Rs. {deduction:>8.2f}")
    print(f"{'Employee • EMP-NGAWANG-001':<30} | Net Monthly: Rs. {net:>8.2f}")
    print(f"{'':30} | OT: Rs.      0.00")
    print("="*60 + "\n")


if __name__ == '__main__':
    print("Creating test payroll data for ngawang sherpa...\n")
    
    # Step 1: Create employee
    employee = create_test_employee()
    
    # Step 2: Create leave record
    create_test_leave()
    
    # Step 3: Show calculation
    show_calculation()
    
    print("✓ Test data created successfully!")
    print("\nNext Steps:")
    print("1. Go to Admin Dashboard → Payroll")
    print("2. Click 'Recalculate Payroll' for current month")
    print("3. View ngawang sherpa's payroll batch")
    print("4. Check Deduction, Net Monthly Salary, and OT columns")
    print("\nLogin Credentials:")
    print("Email: ngawang.sherpa@ems.com")
    print("Password: NgawangTest@123")

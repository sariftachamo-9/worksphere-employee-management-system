import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'ems.db')
if not os.path.exists(db_path):
    # Fallback to root or instance if not found in same dir (though it should be there now)
    db_path = 'database/ems.db'
    if not os.path.exists(db_path):
        db_path = os.path.join('instance', 'ems.db')

print(f"Syncing database: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Add username to users
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN username VARCHAR(80)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        print("Added username to users")
    except sqlite3.OperationalError as e:
        print(f"Note: {e}")

    # Add new fields to contact_queries
    contact_cols = [
        ("is_anonymous", "BOOLEAN DEFAULT 0"),
        ("phone", "VARCHAR(20)"),
        ("subject", "VARCHAR(200)"),
        ("description", "TEXT"),
        ("user_id", "INTEGER")
    ]
    for col_name, col_type in contact_cols:
        try:
            cursor.execute(f"ALTER TABLE contact_queries ADD COLUMN {col_name} {col_type}")
            print(f"Added {col_name} to contact_queries")
        except sqlite3.OperationalError:
            print(f"{col_name} already exists in contact_queries")

    try:
        cursor.execute("ALTER TABLE contact_queries ADD COLUMN admin_reply TEXT")
        print("Added admin_reply to contact_queries")
    except sqlite3.OperationalError:
        print("admin_reply already exists in contact_queries")

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id INTEGER NOT NULL,
                sender_type VARCHAR(20) NOT NULL,
                message TEXT NOT NULL,
                timestamp TIMESTAMP,
                FOREIGN KEY(query_id) REFERENCES contact_queries(id)
            )
        """)
        print("Ensured query_messages table exists")
    except sqlite3.OperationalError as e:
        print(f"Error creating query_messages table: {e}")

    # Add new fields to employee_profiles
    profile_cols = [
        ("personal_email", "VARCHAR(120)"),
        ("phone", "VARCHAR(20)"),
        ("overtime_rate", "FLOAT DEFAULT 0.0"),
        ("leave_allowance", "FLOAT DEFAULT 15.0"),
        ("tax_deduction", "FLOAT DEFAULT 0.0"),
        ("insurance_deduction", "FLOAT DEFAULT 0.0"),
        ("other_deductions", "FLOAT DEFAULT 0.0"),
        ("workshop_end_date", "DATE"),
        ("payment_status", "VARCHAR(20)"),
        ("workshop_status", "VARCHAR(20) DEFAULT 'Ongoing'"),
        ("last_updated", "TIMESTAMP")
    ]
    for col_name, col_type in profile_cols:
        try:
            cursor.execute(f"ALTER TABLE employee_profiles ADD COLUMN {col_name} {col_type}")
            print(f"Added {col_name} to employee_profiles")
        except sqlite3.OperationalError:
            print(f"{col_name} already exists in employee_profiles")

    # Add snapshot fields to payrolls
    payroll_cols = [
        ("snapshot_base_salary", "FLOAT"),
        ("snapshot_hra", "FLOAT"),
        ("snapshot_transport", "FLOAT"),
        ("overtime_earnings", "FLOAT DEFAULT 0.0"),
        ("lop_deduction", "FLOAT DEFAULT 0.0"),
        ("absent_days", "FLOAT DEFAULT 0.0"),
        ("leave_days", "FLOAT DEFAULT 0.0"),
        ("absent_deduction", "FLOAT DEFAULT 0.0"),
        ("leave_deduction", "FLOAT DEFAULT 0.0"),
        ("payment_status", "VARCHAR(20) DEFAULT 'Unpaid'"),
        ("paid_date", "TIMESTAMP"),
        ("status", "VARCHAR(20) DEFAULT 'generated'"),
        ("processed_date", "TIMESTAMP"),
        ("earnings_last_updated", "TIMESTAMP"),
        ("cycle_label", "VARCHAR(20)")
    ]

    for col_name, col_type in payroll_cols:
        try:
            cursor.execute(f"ALTER TABLE payrolls ADD COLUMN {col_name} {col_type}")
            print(f"Added {col_name} to payrolls")
        except sqlite3.OperationalError:
            print(f"{col_name} already exists in payrolls")

    # Migrate existing status data: 'paid' -> 'Paid', 'generated' -> 'Unpaid'
    try:
        cursor.execute("UPDATE payrolls SET payment_status = 'Paid', paid_date = processed_date WHERE status = 'paid'")
        cursor.execute("UPDATE payrolls SET payment_status = 'Unpaid' WHERE status = 'generated' OR status IS NULL")
        cursor.execute("UPDATE payrolls SET status = 'generated' WHERE status IS NULL")
        print("Migrated payment_status values")
    except sqlite3.OperationalError as e:
        print(f"Note: {e}")

    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_user_period ON payrolls(user_id, month, year)")
        print("Ensured uq_payroll_user_period exists")
    except sqlite3.OperationalError as e:
        print(f"Could not create uq_payroll_user_period: {e}")

    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_payroll_cycle_status ON payrolls(year, month, status)")
        print("Ensured idx_payroll_cycle_status exists")
    except sqlite3.OperationalError as e:
        print(f"Could not create idx_payroll_cycle_status: {e}")

    # Create allowed_locations table
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS allowed_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL,
                radius INTEGER DEFAULT 100,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        print("Ensured allowed_locations table exists")
    except sqlite3.OperationalError:
        print("Error creating allowed_locations table")

    # Add is_active to notices
    try:
        cursor.execute("ALTER TABLE notices ADD COLUMN is_active BOOLEAN DEFAULT 1")
        print("Added is_active to notices")
    except sqlite3.OperationalError:
        print("is_active already exists in notices")

    # Create login_logs table
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(80),
                user_id VARCHAR(50),
                role VARCHAR(20),
                latitude FLOAT,
                longitude FLOAT,
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("Ensured login_logs table exists")
    except sqlite3.OperationalError:
        print("Error creating login_logs table")

    conn.commit()
    print("Database sync complete.")
except Exception as e:
    print(f"Error syncing database: {e}")

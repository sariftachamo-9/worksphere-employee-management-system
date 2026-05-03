from app import create_app
from extensions import db
from sqlalchemy import text

app = create_app()
with app.app_context():
    try:
        db.session.execute(text('ALTER TABLE contact_queries ADD COLUMN admin_reply TEXT'))
        db.session.commit()
        print("Successfully added admin_reply column.")
    except Exception as e:
        print(f"Error (maybe column exists?): {e}")


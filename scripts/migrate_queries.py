from app import create_app
from extensions import db
from database.models import ContactQuery, QueryMessage

app = create_app()
with app.app_context():
    # Create the new table
    db.create_all()

    # Migrate existing queries
    queries = ContactQuery.query.all()
    count = 0
    for q in queries:
        # User message
        if q.message or q.description:
            user_msg = QueryMessage(
                query_id=q.id,
                sender_type='user',
                message=(q.description or q.message),
                timestamp=q.created_at
            )
            db.session.add(user_msg)
            count += 1
            
        # Admin message
        if q.admin_reply:
            # We don't have exact timestamp for admin reply, just use created_at + 1 min or current time
            from utils.time_utils import get_nepal_time
            admin_msg = QueryMessage(
                query_id=q.id,
                sender_type='admin',
                message=q.admin_reply,
                timestamp=get_nepal_time()
            )
            db.session.add(admin_msg)
            count += 1
            
    db.session.commit()
    print(f"Migrated {count} query messages.")


import sys
from app import create_app
from extensions import db
from database.models import User
import traceback

app = create_app('development')
with app.test_client() as client:
    with app.app_context():
        user = User.query.filter_by(role='admin').first()
    
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['session_version'] = app.config.get('BOOT_ID')
        
    response = client.get('/admin/remove-staff?role=intern')
    if response.status_code == 500:
        print("FAILED 500")
        print(response.get_data(as_text=True))
    else:
        print(f"SUCCESS {response.status_code}")

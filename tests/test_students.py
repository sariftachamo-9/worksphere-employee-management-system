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
        
    response = client.get('/admin/students')
    if response.status_code == 200:
        html = response.get_data(as_text=True)
        if 'Abhishek Dhungana' in html and 'Ashim Nepal' in html:
            print("SUCCESS: Both are in the HTML")
        else:
            print("FAILED: Not in HTML")
            if 'Abhishek Dhungana' not in html: print("Missing Abhishek")
            if 'Ashim Nepal' not in html: print("Missing Ashim")
    else:
        print(f"FAILED {response.status_code}")

from app import create_app
from database.models import User
app = create_app('development')
with app.test_client() as client:
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['session_version'] = app.config.get('BOOT_ID')
    
    resp = client.get('/admin/api/dashboard/details?type=absent')
    print(f"Status: {resp.status_code}")
    data = resp.get_json()
    print(f"Absent Count: {len(data)}")

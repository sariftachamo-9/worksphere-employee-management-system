from app import create_app
from database.models import User
app = create_app('development')
with app.test_client() as client:
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['session_version'] = app.config.get('BOOT_ID')
    
    for t in ['queries', 'joinings', 'completed_students']:
        resp = client.get(f'/admin/api/dashboard/details?type={t}')
        print(f"Type: {t}, Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.get_json()
            print(f"Count: {len(data)}")
            if len(data) > 0:
                print(f"Sample: {data[0]}")

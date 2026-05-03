from app import create_app
from database.models import User
app = create_app('development')
with app.test_client() as client:
    with app.app_context():
        admin = User.query.filter_by(role='admin').first()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['session_version'] = app.config.get('BOOT_ID')
    response = client.get('/admin/api/stats')
    print("Status:", response.status_code)
    if response.status_code == 200:
        data = response.get_json()
        print("Completed Courses:", data.get('completed_courses'))
        print("Removed Staff:", data.get('removed_staff'))

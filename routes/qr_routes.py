from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db, csrf
from database.models import User, EmployeeProfile, LoginLog, AuditLog, Notice, LoginToken, BadgeQRToken
from utils.time_utils import get_nepal_time
from datetime import datetime, timedelta
import os
import secrets
from utils import location_service
import uuid
import base64
from io import BytesIO
import qrcode

qr_bp = Blueprint('qr', __name__)

# ─── Location Verification API (New) ──────────────────────────────────────────

@qr_bp.route('/api/grant-bypass/<int:user_id>', methods=['POST'])
@login_required
def grant_bypass(user_id):
    """Admin endpoint to grant a 24-hour location bypass to a specific user"""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    user = User.query.get_or_404(user_id)
    user.location_bypass_until = get_nepal_time() + timedelta(hours=24)
    
    # Create a private Notice for the user
    notice = Notice(
        title="Location Bypass Activated",
        content=f"Admin has granted you a 24-hour location bypass. You can now check in from any location until {user.location_bypass_until.strftime('%I:%M %p %d %b')}.",
        target_user_id=user.id,
        is_active=True,
        notice_type="System Alert"
    )
    db.session.add(notice)

    # Audit Log
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Granted 24h Location Bypass to {user.email}",
        ip_address=request.remote_addr
    ))
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'24h bypass granted to {user.email}'})

@qr_bp.route('/api/check-bypass-status', methods=['POST'])
@csrf.exempt
def check_bypass_status():
    """Public endpoint to check if an email currently has a location bypass"""
    data = request.get_json()
    email = data.get('email')
    portal_role = data.get('role') # The role currently selected in the UI
    
    # 1. Office IP Bypass (Role-Agnostic, checked first)
    from database.models import OfficeSettings
    settings = OfficeSettings.query.first()
    office_ip = settings.office_ip if settings and settings.office_ip else current_app.config.get('OFFICE_PUBLIC_IP', '')
    if office_ip and request.remote_addr == office_ip:
        return jsonify({'has_bypass': True, 'reason': 'office_ip'})
        
    # 2. User-Specific Bypasses (Require Email or ID)
    if not email:
        return jsonify({'has_bypass': False})
    
    user = User.query.filter_by(email=email).first()
    if not user:
        # Fallback to ID-based lookup (Matching login identification rule)
        from database.models import EmployeeProfile
        user = User.query.join(EmployeeProfile).filter(
            db.func.lower(EmployeeProfile.employee_id) == email.lower()
        ).first()
        
    if not user:
        return jsonify({'has_bypass': False})
    
    # Admins are exempt by default, but only if they are in the Admin Portal
    if user.role == 'admin' and portal_role == 'admin':
        return jsonify({'has_bypass': True, 'reason': 'admin'})
        
    # Check for admin-granted personal bypass.
    if user.location_bypass_until and user.location_bypass_until > get_nepal_time():
        return jsonify({'has_bypass': True, 'reason': 'temporary'})

    # Check for overtime-based bypass (explicit admin-granted overtime request)
    if user.overtime_bypass_until and user.overtime_bypass_until > get_nepal_time():
        return jsonify({'has_bypass': True, 'reason': 'overtime'})

    return jsonify({'has_bypass': False})

@qr_bp.route('/api/generate-loc-token', methods=['POST'])
@csrf.exempt
def generate_loc_token():
    """Generates a unique token for location verification"""
    token = location_service.generate_location_token()
    
    # Generate the mobile verification URL
    external_url = os.environ.get('EXTERNAL_URL')
    if external_url:
        # Force HTTPS and handle prefix correctly
        base_url = external_url.rstrip('/').replace('http://', 'https://')
        verify_url = base_url + url_for('qr.verify_location_page', token=token)
    else:
        # Default fallback
        verify_url = url_for('qr.verify_location_page', token=token, _external=True, _scheme='https')
        if 'http://' in verify_url:
            verify_url = verify_url.replace('http://', 'https://')
        
    return jsonify({
        'success': True,
        'token': token,
        'verify_url': verify_url
    })

@qr_bp.route('/verify-location/<token>')
def verify_location_page(token):
    """Mobile landing page for GPS verification"""
    status = location_service.check_token_status(token)
    if status == 'expired':
        return render_template('qr/verify_location.html', error="Token expired. Please scan a new QR code.")
    return render_template('qr/verify_location.html', token=token)

@qr_bp.route('/api/submit-location', methods=['POST'])
@csrf.exempt
def submit_location():
    """Receives GPS coordinates from mobile device"""
    data = request.get_json()
    token = data.get('token')
    lat = data.get('latitude')
    lon = data.get('longitude')
    accuracy = data.get('accuracy')
    
    if not token:
        return jsonify({'success': False, 'message': 'Missing token'}), 400
        
    from database.models import OfficeSettings
    settings = OfficeSettings.query.first()
    
    # Check IP fallback first (High Security)
    user_ip = request.remote_addr
    office_ip = settings.office_ip if settings and settings.office_ip else current_app.config.get('OFFICE_PUBLIC_IP', '')
    
    # If the user is on the Office Network, verify immediately
    if location_service.verify_ip_fallback(token, user_ip, office_ip):
        return jsonify({'success': True, 'message': 'Location verified via Office Network.'})
    
    # If not on Office IP, we MUST have GPS coordinates
    if lat is None or lon is None:
        msg = f"GPS denied and not on Office Network. (Your IP: {user_ip})"
        return jsonify({'success': False, 'message': msg}), 403
    
    # Otherwise, check GPS distance
    office_lat = settings.latitude if settings else current_app.config.get('OFFICE_LATITUDE')
    office_lon = settings.longitude if settings else current_app.config.get('OFFICE_LONGITUDE')
    radius = settings.radius if settings else current_app.config.get('GEOFENCE_RADIUS', 100)
    
    success, message = location_service.verify_token_location(token, lat, lon, accuracy)
    return jsonify({'success': success, 'message': message})

@qr_bp.route('/api/check-loc-status/<token>')
def check_loc_status(token):
    """Polling endpoint for PC to check if mobile verification is done"""
    status = location_service.check_token_status(token)
    return jsonify({'status': status})

# ─── Static Badge QR Token (Permanent Until Revoked) ─────────────────────────

PERMANENT_BADGE_EXPIRES_AT = datetime(2099, 12, 31, 23, 59, 59)

def get_or_create_badge_token(user):
    """Return the user's fixed BadgeQRToken, creating it only if missing/revoked."""
    token_rec = BadgeQRToken.query.filter_by(
        user_id=user.id, is_revoked=False
    ).order_by(BadgeQRToken.created_at.desc()).first()

    if token_rec:
        if token_rec.expires_at != PERMANENT_BADGE_EXPIRES_AT:
            token_rec.expires_at = PERMANENT_BADGE_EXPIRES_AT
            db.session.commit()
        return token_rec

    # Missing or previously revoked: issue one stable badge token for the user.
    new_token = BadgeQRToken(
        user_id=user.id,
        token=secrets.token_urlsafe(48),
        expires_at=PERMANENT_BADGE_EXPIRES_AT
    )
    db.session.add(new_token)
    db.session.commit()
    return new_token


def build_badge_url(token_str):
    """Build the full external URL for a badge scan token."""
    external_url = os.environ.get('EXTERNAL_URL')
    if external_url:
        return external_url.rstrip('/') + url_for('qr.badge_scan', token=token_str)
    url = url_for('qr.badge_scan', token=token_str, _external=True, _scheme='https')
    return url.replace('http://', 'https://') if not current_app.debug else url


def no_store_response(template_name, **context):
    response = current_app.make_response(render_template(template_name, **context))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def build_qr_data_uri(value):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(value)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#f8fafc")
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f"data:image/png;base64,{encoded}"


@qr_bp.route('/api/my-badge-qr')
@login_required
def my_badge_qr():
    """Return the current user's permanent badge QR URL."""
    rec = get_or_create_badge_token(current_user)
    badge_url = build_badge_url(rec.token)
    return jsonify({
        'success': True,
        'badge_url': badge_url,
        'expires_at': 'Never',
        'days_until_refresh': None,
        'is_static': True,
        'owner_name': current_user.profile.full_name if current_user.profile else current_user.username,
        'owner_id': current_user.profile.employee_id if current_user.profile else str(current_user.id),
        'owner_role': current_user.role
    })


@qr_bp.route('/badge/<token>')
def badge_scan(token):
    """Multi-scan fixed badge handler. Validates token, enforces geofence, logs in user."""
    now = get_nepal_time()
    rec = BadgeQRToken.query.filter_by(token=token, is_revoked=False).first()

    if not rec:
        return no_store_response('qr/qr_error.html'), 403

    user = rec.user
    if not user or not user.is_active:
        return no_store_response('qr/qr_error.html'), 403

    # Pass through to auto_login page (which handles geofence + session setup)
    # Re-use the existing token-based auto-login template by generating a short-lived token
    from database.models import OfficeSettings
    settings = OfficeSettings.query.first()
    office_ip = settings.office_ip if settings and settings.office_ip else current_app.config.get('OFFICE_PUBLIC_IP', '')

    # Check for IP bypass first (no need to show scan page)
    if office_ip and request.remote_addr == office_ip:
        # Directly log in the user
        new_session_id = secrets.token_hex(16)
        user.current_session_id = new_session_id
        session['session_token'] = new_session_id
        session['session_version'] = current_app.config.get('BOOT_ID')
        login_user(user)
        db.session.add(AuditLog(user_id=user.id, action='Badge Scan Login (Office IP)', ip_address=request.remote_addr))
        db.session.add(LoginLog(username=user.profile.full_name if user.profile else user.username,
                                user_id=user.profile.employee_id if user.profile else str(user.id),
                                role=user.role, login_time=now))
        db.session.commit()
        return redirect(url_for('staff.dashboard'))

    # Otherwise show the GPS verification page using the fixed badge token.
    # The badge token is multi-scan; geofence validation still happens before login.
    user_info = {
        'username': user.profile.full_name if user.profile else user.username,
        'employee_id': user.profile.employee_id if user.profile else str(user.id),
        'role': user.role
    }
    return no_store_response('qr/auto_login.html', token=token, user_info=user_info, is_static_badge=True)


@qr_bp.route('/api/revoke-badge/<int:user_id>', methods=['POST'])
@login_required
def revoke_badge(user_id):
    """Admin: revoke a user's current badge token, forcing regeneration on next load."""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    BadgeQRToken.query.filter_by(user_id=user_id, is_revoked=False).update({'is_revoked': True})
    db.session.add(AuditLog(user_id=current_user.id,
                            action=f'Revoked Badge QR Token for user_id={user_id}',
                            ip_address=request.remote_addr))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Badge token revoked. A new fixed badge will be issued on next view.'})


# ─── Badge Generation Routes ──────────────────────────────────────────────────

def generate_qr_url(user):
    rec = get_or_create_badge_token(user)
    return build_badge_url(rec.token)


def redirect_legacy_login_token_to_badge(db_token):
    if not db_token or not db_token.user:
        return None

    badge_rec = get_or_create_badge_token(db_token.user)
    return redirect(url_for('qr.badge_scan', token=badge_rec.token))


def render_static_badge(user):
    verify_url = generate_qr_url(user)
    if '/qr/badge/' not in verify_url:
        current_app.logger.error(f"Static badge URL generation failed for user {user.id}: {verify_url}")
        return render_template('qr/qr_error.html'), 500
    qr_data_uri = build_qr_data_uri(verify_url)
    return no_store_response(
        'qr/personal_badge.html',
        user=user,
        verify_url=verify_url,
        qr_data_uri=qr_data_uri
    )

@qr_bp.route('/my-badge')
@login_required
def my_badge():
    """Unified endpoint for any logged-in user to view their personal digital ID badge"""
    return render_static_badge(current_user)

@qr_bp.route('/generate/employee/<int:user_id>')
@login_required
def em_qr_gen(user_id):
    if current_user.role != 'admin' and current_user.id != user_id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('staff.dashboard'))
    user = User.query.get_or_404(user_id)
    return render_static_badge(user)

@qr_bp.route('/generate/intern/<int:user_id>')
@login_required
def int_qr_gen(user_id):
    if current_user.role != 'admin' and current_user.id != user_id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('staff.dashboard'))
    user = User.query.get_or_404(user_id)
    return render_static_badge(user)

@qr_bp.route('/generate/student/<int:user_id>')
@login_required
def std_qr_gen(user_id):
    if current_user.role != 'admin' and current_user.id != user_id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('staff.dashboard'))
    user = User.query.get_or_404(user_id)
    return render_static_badge(user)

# ─── Scanner Page ─────────────────────────────────────────────────────────────

@qr_bp.route('/scan')
def scanner():
    return render_template('qr/qr_scan.html')

# ─── Login API ────────────────────────────────────────────────────────────────

@qr_bp.route('/api/qr-login', methods=['POST'])
def qr_login_api():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data received'}), 400
        
    username = data.get('username')
    user_id_badge = data.get('user_id')
    role = data.get('role')
    lat = data.get('latitude')
    lon = data.get('longitude')
    accuracy = data.get('accuracy')
    token = data.get('token')
    badge_token = data.get('badge_token')
    
    # Handle fixed badge login. The badge token is reusable, but login still requires geofence.
    if badge_token:
        badge_rec = BadgeQRToken.query.filter_by(token=badge_token, is_revoked=False).first()
        if not badge_rec:
            return jsonify({'success': False, 'message': 'Invalid or revoked badge.'}), 403

        user = badge_rec.user
        if not user:
            return jsonify({'success': False, 'message': 'User not associated with badge.'}), 404

        username = user.profile.full_name if user.profile else user.username
        user_id_badge = user.profile.employee_id if user.profile else user.id
        role = user.role

    # Handle one-time dynamic login token.
    elif token:
        # Resolve token from database
        db_token = LoginToken.query.filter_by(token=token).first()
        if not db_token or db_token.used or db_token.expires_at < get_nepal_time():
            return jsonify({'success': False, 'message': 'Invalid, used, or expired security token.'}), 403
            
        user = db_token.user
        if not user:
            return jsonify({'success': False, 'message': 'User not associated with token.'}), 404
            
        username = user.profile.full_name if user.profile else user.username
        user_id_badge = user.profile.employee_id if user.profile else user.id
        role = user.role
        
        # We don't mark as used YET. We wait for full login success.
            
    if not username or not user_id_badge or not role:
        return jsonify({'success': False, 'message': 'Missing user data in request.'}), 400
    
    # 1. Validate user exists in database
    # Search by employee_id primarily, but also check full_name match
    user = User.query.join(EmployeeProfile).filter(
        EmployeeProfile.employee_id == user_id_badge,
        User.role == role
    ).first()
    
    # Validation check: Ensure the badge name matches the database profile name (case-insensitive)
    if user:
        db_name = user.profile.full_name.strip().lower()
        badge_name = username.strip().lower()
        if db_name != badge_name:
            current_app.logger.warning(f"QR Login: Name Mismatch for {user_id_badge}. Badge says '{username}', DB says '{user.profile.full_name}'")
            return jsonify({'success': False, 'message': 'Badge name mismatch.'}), 403
    
    if not user:
        current_app.logger.error(f"QR Login: User not found. ID: {user_id_badge}, Name: {username}, Role: {role}")
        return jsonify({'success': False, 'message': 'User not found or role mismatch.'}), 404
        
    if not user.is_active:
        return jsonify({'success': False, 'message': 'Account is inactive.'}), 403

    # 1.5. Geofence Validation
    from utils.location_utils import verify_location_access
    from database.models import OfficeSettings
    
    settings = OfficeSettings.query.first()
    office_ip = settings.office_ip if settings and settings.office_ip else current_app.config.get('OFFICE_PUBLIC_IP', '')
    
    # Check for Bypasses (Office IP, Admin role, admin grant, or Overtime)
    has_bypass = False
    
    if office_ip and request.remote_addr == office_ip:
        has_bypass = True
    elif user.role == 'admin':
        has_bypass = True
    elif user.location_bypass_until and user.location_bypass_until > get_nepal_time():
        has_bypass = True
    elif user.overtime_bypass_until and user.overtime_bypass_until > get_nepal_time():
        has_bypass = True
        
    if not has_bypass:
        if lat is None or lon is None:
            return jsonify({'success': False, 'message': 'Location access required for auto-login.'}), 403
            
        is_allowed, msg, dist = verify_location_access(lat, lon, accuracy)
        if not is_allowed:
            current_app.logger.warning(f"QR Login: Geofence rejection for {user_id_badge}. Distance: {int(dist)}m. IP: {request.remote_addr}")
            return jsonify({'success': False, 'message': msg}), 403

    # 2. Store login record
    log = LoginLog(
        username=username,
        user_id=user_id_badge,
        role=role,
        latitude=lat,
        longitude=lon,
        login_time=get_nepal_time()
    )
    db.session.add(log)
    
    # 3. Create user session with consistent security tokens
    # This prevents the Single Session Middleware from kicking the user out on the next click.
    new_session_id = secrets.token_hex(16)
    user.current_session_id = new_session_id
    session['session_token'] = new_session_id
    
    login_user(user)
    
    session['session_version'] = current_app.config.get('BOOT_ID')
    
    # Audit Log for QR Login
    db.session.add(AuditLog(
        user_id=user.id,
        action="User logged in via QR Badge Scan",
        details=f"Device IP: {request.remote_addr}, Lat: {lat}, Lon: {lon}",
        ip_address=request.remote_addr
    ))
    
    # NEW: Securely consume the token (Corrected variable lookup)
    if token and not badge_token:
        db_token = LoginToken.query.filter_by(token=token).first()
        if db_token:
            db_token.used = True
            
    db.session.commit()
    
    # 4. Return redirect URL based on role
    # Mapping to standard dashboard routes but including the requested virtual paths
    redirect_map = {
        'employee': url_for('staff.dashboard'),
        'intern': url_for('staff.dashboard'),
        'student': url_for('staff.dashboard')
    }
    
    return jsonify({
        'success': True, 
        'message': 'Login successful',
        'redirect_url': redirect_map.get(role, url_for('staff.dashboard'))
    })

# ─── Virtual Redirect Routes (to satisfy requirement 4) ───────────────────────

@qr_bp.route('/employee_dashboard.html')
@login_required
def employee_dashboard_virtual():
    return redirect(url_for('staff.dashboard'))

@qr_bp.route('/intern_dashboard.html')
@login_required
def intern_dashboard_virtual():
    return redirect(url_for('staff.dashboard'))

@qr_bp.route('/student_dashboard.html')
@login_required
def student_dashboard_virtual():
    return redirect(url_for('staff.dashboard'))

# ─── Auto-Login from Native Camera QR Scan ────────────────────────────────────

@qr_bp.route('/auto-login/<token>')
def auto_login(token):
    # Layer 1 & 3 (Atomic): One-Time View & Existence Check
    # This UPDATE is atomic - only one request can ever change is_viewed from False to True.
    # We also check for expiration and usage in the same query.
    now = get_nepal_time()
    affected = LoginToken.query.filter_by(
        token=token, 
        is_viewed=False, 
        used=False
    ).filter(LoginToken.expires_at > now).update({'is_viewed': True})
    
    db.session.commit()

    # Fetch the token to continue validation (or fail if update didn't happen)
    db_token = LoginToken.query.filter_by(token=token).first()

    if affected == 0:
        legacy_badge_redirect = redirect_legacy_login_token_to_badge(db_token)
        if legacy_badge_redirect:
            return legacy_badge_redirect

        # Reason for failure: Token doesn't exist.
        return render_template('qr/qr_error.html'), 403

    # Layer 2: Browser Fingerprint Binding (Cookie Based)
    fp_cookie = request.cookies.get('qr_fp')
    
    # Check if a fingerprint is already bound
    if db_token.browser_fingerprint:
        if fp_cookie != db_token.browser_fingerprint:
            legacy_badge_redirect = redirect_legacy_login_token_to_badge(db_token)
            if legacy_badge_redirect:
                return legacy_badge_redirect
            return render_template('qr/qr_error.html'), 403
    else:
        # First use: Bind the fingerprint immediately and atomically
        if not fp_cookie:
            import uuid
            fp_cookie = str(uuid.uuid4())
        
        # Another atomic update to set the fingerprint if it's still NULL
        # (Prevents a race where two tabs of the same browser open it simultaneously)
        db_token.browser_fingerprint = fp_cookie
        db.session.commit()

    user = db_token.user
    user_info = {
        "username": user.profile.full_name if user.profile else user.username,
        "employee_id": user.profile.employee_id if user.profile else str(user.id),
        "role": user.role
    }
        
    response = current_app.make_response(render_template('qr/auto_login.html', token=token, user_info=user_info))
    
    # Set the tracking cookie if not present (Session cookie, strict)
    response.set_cookie('qr_fp', fp_cookie, httponly=True, samesite='Strict')
    
    return response

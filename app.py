import os
import shutil
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
import urllib.parse
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, g)
from PIL import Image
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# App Configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, 'database.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_IMAGE_SIZE = (800, 800)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------------------------------------------------------------------
# Database Helpers
# ---------------------------------------------------------------------------
def check_expired_reservations(db):
    """Finds all orders with status 'Reserved' that have expired,
    restores their stock, and marks them as 'Expired'."""
    now_utc = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    cur = db.execute(
        "SELECT id FROM orders WHERE status = 'Reserved' AND reserved_until < ?",
        [now_utc]
    )
    expired_orders = cur.fetchall()
    
    if expired_orders:
        for order in expired_orders:
            order_id = order['id']
            # Fetch items in this order
            items_cur = db.execute(
                'SELECT product_id, quantity FROM order_items WHERE order_id = ?',
                [order_id]
            )
            items = items_cur.fetchall()
            for item in items:
                db.execute(
                    'UPDATE products SET stock = stock + ? WHERE id = ?',
                    [item['quantity'], item['product_id']]
                )
            # Update order status to Expired and clear reservation time
            db.execute(
                "UPDATE orders SET status = 'Expired', reserved_until = NULL WHERE id = ?",
                [order_id]
            )
        db.commit()

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        # Run cleanup here without recursive get_db loop
        if not g.get('cleaning_reservations'):
            g.cleaning_reservations = True
            try:
                check_expired_reservations(g.db)
            finally:
                g.cleaning_reservations = False
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initialize database from schema.sql only if tables don't exist yet.
    Also inserts any new default settings that may be missing (migrations)."""
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    # Check if settings table already exists
    existing = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
    ).fetchone()
    if not existing:
        with open(os.path.join(BASE_DIR, 'schema.sql'), 'r', encoding='utf-8') as f:
            db.executescript(f.read())
        db.commit()
    
    # --- Migrations: add reserved_until column if missing ---
    try:
        db.execute("ALTER TABLE orders ADD COLUMN reserved_until TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass # Already exists

    # --- Migrations: add post_office and district columns to customers if missing ---
    try:
        db.execute("ALTER TABLE customers ADD COLUMN post_office TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE customers ADD COLUMN district TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass

    # --- Migrations: add image2 column to products if missing ---
    try:
        db.execute("ALTER TABLE products ADD COLUMN image2 TEXT")
        db.commit()
    except sqlite3.OperationalError:
        pass
        
    # --- Migrations: insert missing default settings for existing installs ---
    defaults = [
        ('show_out_of_stock', '1'),  # '1' = show them, '0' = hide them
        ('stock_reduction_mode', 'reserve'),  # 'reserve' = 15 min, 'manual' = manual updates
        ('reservation_minutes', '15'),  # hold stock for 15 minutes by default
        ('maintenance_mode', '0'),  # '0' = normal, '1' = storefront offline (maintenance mode)
        ('maintenance_message', 'We are currently updating our stock. Kindly visit later!'),
        ('shop_logo', ''),
    ]
    for key, value in defaults:
        db.execute(
            'INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
            [key, value]
        )
    db.commit()
    db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur

# ---------------------------------------------------------------------------
# Settings Helper
# ---------------------------------------------------------------------------
def get_setting(key, default=''):
    row = query_db('SELECT value FROM settings WHERE key = ?', [key], one=True)
    return row['value'] if row else default

def set_setting(key, value):
    execute_db('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', [key, value])

def get_all_settings():
    rows = query_db('SELECT key, value FROM settings')
    return {row['key']: row['value'] for row in rows}

# ---------------------------------------------------------------------------
# Password Helpers
# ---------------------------------------------------------------------------
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ---------------------------------------------------------------------------
# Image Helpers
# ---------------------------------------------------------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_image(file):
    """Save and resize uploaded image, return filename."""
    if not file or not allowed_file(file.filename):
        return None
    ext = file.filename.rsplit('.', 1)[1].lower()
    unique_name = f"{secrets.token_hex(8)}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, unique_name)
    img = Image.open(file)
    img = img.convert('RGB')
    img.thumbnail(MAX_IMAGE_SIZE, Image.LANCZOS)
    img.save(filepath, optimize=True, quality=85)
    return unique_name

def save_logo_image(file):
    """Save and process uploaded shop logo, preserving RGBA transparency for PNG/WEBP."""
    if not file or not allowed_file(file.filename):
        return None
    ext = file.filename.rsplit('.', 1)[1].lower()
    unique_name = f"logo_{secrets.token_hex(6)}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, unique_name)
    img = Image.open(file)
    # Preserve RGBA transparency for png/webp
    if ext in ('png', 'webp') and ('A' in img.getbands() or img.mode in ('RGBA', 'LA', 'P')):
        img = img.convert('RGBA')
        img.thumbnail((400, 400), Image.LANCZOS)
        img.save(filepath, optimize=True)
    else:
        img = img.convert('RGB')
        img.thumbnail((400, 400), Image.LANCZOS)
        img.save(filepath, optimize=True, quality=90)
    return unique_name

# ---------------------------------------------------------------------------
# Auth Decorator
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

# ---------------------------------------------------------------------------
# Template Filters
# ---------------------------------------------------------------------------
@app.template_filter('to_ist')
def to_ist_filter(utc_str):
    if not utc_str:
        return ""
    try:
        clean_str = utc_str.split('.')[0]
        dt = datetime.strptime(clean_str, '%Y-%m-%d %H:%M:%S')
        ist_dt = dt + timedelta(hours=5, minutes=30)
        return ist_dt.strftime('%Y-%m-%d %I:%M %p IST')
    except Exception:
        return utc_str

# ---------------------------------------------------------------------------
# Storage Balance Helper (Admin Panel)
# ---------------------------------------------------------------------------
def get_storage_stats():
    """Returns disk and upload folder storage metrics for the admin panel."""
    try:
        total, used, free = shutil.disk_usage(UPLOAD_FOLDER)

        def format_bytes(b):
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if b < 1024.0:
                    return f"{b:.1f} {unit}" if unit in ['MB', 'GB', 'TB'] else f"{int(b)} {unit}"
                b /= 1024.0
            return f"{b:.1f} PB"

        used_pct = round((used / total) * 100, 1) if total > 0 else 0
        free_pct = round((free / total) * 100, 1) if total > 0 else 0

        # Uploads folder size & file count
        uploads_size = 0
        uploads_count = 0
        if os.path.exists(UPLOAD_FOLDER):
            for entry in os.scandir(UPLOAD_FOLDER):
                if entry.is_file():
                    uploads_size += entry.stat().st_size
                    uploads_count += 1

        # Database file size
        db_size = os.path.getsize(DATABASE) if os.path.exists(DATABASE) else 0

        # Status badge
        status = 'healthy' if free_pct > 15 else ('warning' if free_pct > 5 else 'critical')

        return {
            'total_bytes': total,
            'used_bytes': used,
            'free_bytes': free,
            'total_human': format_bytes(total),
            'used_human': format_bytes(used),
            'free_human': format_bytes(free),
            'used_pct': used_pct,
            'free_pct': free_pct,
            'uploads_bytes': uploads_size,
            'uploads_human': format_bytes(uploads_size),
            'uploads_count': uploads_count,
            'db_bytes': db_size,
            'db_human': format_bytes(db_size),
            'status': status
        }
    except Exception:
        return {
            'total_human': 'N/A', 'used_human': 'N/A', 'free_human': 'N/A',
            'used_pct': 0, 'free_pct': 100, 'uploads_human': '0 MB',
            'uploads_count': 0, 'db_human': '0 KB', 'status': 'healthy'
        }

# ---------------------------------------------------------------------------
# Context Processor – injects shop settings and storage stats into templates
# ---------------------------------------------------------------------------
@app.context_processor
def inject_settings():
    settings = get_all_settings()
    ctx = dict(settings=settings)
    if request.path.startswith('/admin'):
        ctx['storage_stats'] = get_storage_stats()
    return ctx


# ===========================================================================
# CUSTOMER ROUTES
# ===========================================================================

@app.route('/')
def index():
    search = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()

    # Price filter params
    min_price_raw = request.args.get('min_price', '').strip()
    max_price_raw = request.args.get('max_price', '').strip()
    try:
        min_price = float(min_price_raw) if min_price_raw else None
    except ValueError:
        min_price = None
    try:
        max_price = float(max_price_raw) if max_price_raw else None
    except ValueError:
        max_price = None

    # Respect the admin toggle: hide out-of-stock products if disabled
    show_oos = get_setting('show_out_of_stock', '1')

    query = 'SELECT * FROM products WHERE 1=1'
    args = []
    if show_oos == '0':
        # Hide products with zero stock entirely from the customer page
        query += ' AND stock > 0'
    if search:
        query += ' AND (name LIKE ? OR description LIKE ?)'
        args += [f'%{search}%', f'%{search}%']
    if category:
        query += ' AND category = ?'
        args.append(category)
    if min_price is not None:
        query += ' AND price >= ?'
        args.append(min_price)
    if max_price is not None:
        query += ' AND price <= ?'
        args.append(max_price)
    # Order in-stock products first, then by newest addition
    query += ' ORDER BY CASE WHEN stock > 0 THEN 0 ELSE 1 END ASC, created_at DESC'

    products = query_db(query, args)

    # Distinct categories for the filter bar (only from visible products)
    cat_query = 'SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != ""'
    if show_oos == '0':
        cat_query += ' AND stock > 0'
    cat_query += ' ORDER BY category'
    categories = [row['category'] for row in query_db(cat_query)]

    # Price range of ALL visible products (for placeholder hints)
    price_range = query_db(
        'SELECT MIN(price) as min_p, MAX(price) as max_p FROM products WHERE 1=1' +
        (' AND stock > 0' if show_oos == '0' else ''),
        one=True
    )

    return render_template('index.html',
                           products=products,
                           categories=categories,
                           search=search,
                           active_category=category,
                           min_price=min_price_raw,
                           max_price=max_price_raw,
                           price_range=price_range)


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = query_db('SELECT * FROM products WHERE id = ?', [product_id], one=True)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('index'))
    # Related products (same category, different id)
    related = query_db(
        'SELECT * FROM products WHERE category = ? AND id != ? AND stock > 0 LIMIT 4',
        [product['category'], product_id]
    )
    return render_template('product_detail.html', product=product, related=related)


@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if get_setting('maintenance_mode', '0') == '1':
        if request.method == 'POST':
            return jsonify({'success': False, 'error': get_setting('maintenance_message', 'Store is currently undergoing maintenance. Please try again later.')})
        else:
            flash(get_setting('maintenance_message', 'Store is currently undergoing maintenance. Please try again later.'), 'info')
            return redirect(url_for('index'))

    if request.method == 'POST':
        # Collect cart items from hidden fields
        product_ids = request.form.getlist('product_id[]')
        quantities  = request.form.getlist('quantity[]')

        if not product_ids:
            return jsonify({'success': False, 'error': 'Your cart is empty.'})

        # Validate stock for each item
        items = []
        total = 0.0
        for pid, qty in zip(product_ids, quantities):
            pid = int(pid)
            qty = int(qty)
            product = query_db('SELECT * FROM products WHERE id = ?', [pid], one=True)
            if not product:
                return jsonify({'success': False, 'error': 'A product in your cart no longer exists.'})
            if product['stock'] < qty:
                # Compile current database stock levels for items in checkout request
                stock_updates = {}
                for check_pid in product_ids:
                    p_row = query_db('SELECT stock FROM products WHERE id = ?', [int(check_pid)], one=True)
                    stock_updates[int(check_pid)] = p_row['stock'] if p_row else 0
                return jsonify({
                    'success': False,
                    'error': f'"{product["name"]}" only has {product["stock"]} item(s) left in stock.',
                    'stock_updates': stock_updates
                })
            items.append({'product': product, 'quantity': qty})
            total += product['price'] * qty

        # Customer details
        name        = request.form.get('name', '').strip()
        phone       = request.form.get('phone', '').strip()
        whatsapp    = request.form.get('whatsapp', '').strip()
        address     = request.form.get('address', '').strip()
        post_office = request.form.get('post_office', '').strip()
        district    = request.form.get('district', '').strip()
        pincode     = request.form.get('pincode', '').strip()
        notes       = request.form.get('notes', '').strip()

        if not all([name, phone, whatsapp, address, post_office, district, pincode]):
            return jsonify({'success': False, 'error': 'Please fill in all required fields.'})

        # Save customer
        db = get_db()
        cur = db.execute(
            'INSERT INTO customers (name, phone, whatsapp, address, pincode, post_office, district) VALUES (?,?,?,?,?,?,?)',
            [name, phone, whatsapp, address, pincode, post_office, district]
        )
        customer_id = cur.lastrowid

        # Get stock reduction mode setting
        stock_mode = get_setting('stock_reduction_mode', 'reserve')

        if stock_mode == 'manual':
            # Save order with Pending status and no expiration
            cur = db.execute(
                'INSERT INTO orders (customer_id, total, status, reserved_until) VALUES (?,?,?,?)',
                [customer_id, total, 'Pending', None]
            )
            order_id = cur.lastrowid
            
            # Save order items without reducing stock
            for item in items:
                pid = item['product']['id']
                qty = item['quantity']
                db.execute(
                    'INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?,?,?,?)',
                    [order_id, pid, qty, item['product']['price']]
                )
        else:
            # Save order with Reserved status and dynamic expiration duration
            res_mins = int(get_setting('reservation_minutes', '15'))
            reserved_until = (datetime.utcnow() + timedelta(minutes=res_mins)).strftime('%Y-%m-%d %H:%M:%S')
            cur = db.execute(
                'INSERT INTO orders (customer_id, total, status, reserved_until) VALUES (?,?,?,?)',
                [customer_id, total, 'Reserved', reserved_until]
            )
            order_id = cur.lastrowid

            # Save order items and reduce stock
            for item in items:
                pid = item['product']['id']
                qty = item['quantity']
                db.execute(
                    'INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?,?,?,?)',
                    [order_id, pid, qty, item['product']['price']]
                )
                db.execute('UPDATE products SET stock = stock - ? WHERE id = ?', [qty, pid])

        db.commit()

        # Build WhatsApp message
        shop_name = get_setting('shop_name', 'Our Shop')
        wa_number = get_setting('whatsapp_number', '')
        currency  = get_setting('currency_symbol', '₹')

        lines = [
            f"🛍️ *New Order from {shop_name}!*\n",
            f"📋 *Order ID:* #{order_id}",
            f"👤 *Customer:* {name}",
            f"📞 *Phone:* {phone}",
            f"📍 *Address:* {address}",
        ]
        if post_office:
            lines.append(f"📦 *Post Office (P.O.):* {post_office}")
        if district:
            lines.append(f"🏙️ *District:* {district}")
        lines.append(f"📮 *Pincode:* {pincode}")
        if notes:
            lines.append(f"📝 *Notes:* {notes}")
        lines.append("\n🛒 *Items Ordered:*")
        for item in items:
            p = item['product']
            lines.append(f"  • {item['quantity']} x {p['name']} — {currency}{p['price']:.2f}")
        lines.append(f"\n💰 *Total Amount:* {currency}{total:.2f} + Delivery Charges")
        wa_message = '\n'.join(lines)

        # Store order info in session for the order success page
        session['last_order'] = {
            'customer_name': name,
            'order_id': order_id,
            'currency': currency,
            'total': total,
            'wa_number': wa_number,
            'wa_message': wa_message
        }

        # Return JSON containing redirect URL to local success page
        return jsonify({'success': True, 'redirect_url': url_for('order_success')})

    # GET – render the checkout page with cart data from query params
    return render_template('checkout.html')


@app.route('/order-success')
def order_success():
    order_data = session.get('last_order', None)
    if not order_data:
        return redirect(url_for('index'))
    return render_template('order_success.html', order=order_data)


# API: get product info (for cart validation)
@app.route('/api/product/<int:product_id>')
def api_product(product_id):
    product = query_db('SELECT id, name, price, stock, image, image2 FROM products WHERE id = ?', [product_id], one=True)
    if not product:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(dict(product))


# Serve admin service worker at root of admin scope
@app.route('/admin-sw.js')
def admin_sw():
    from flask import send_from_directory
    return send_from_directory('static', 'admin-sw.js',
                               mimetype='application/javascript')


# ===========================================================================
# ADMIN ROUTES
# ===========================================================================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        stored_user = get_setting('admin_username', 'admin')
        stored_pass = get_setting('admin_password', 'admin123')
        # Support both plain and hashed passwords
        if username == stored_user and (
            password == stored_pass or hash_password(password) == stored_pass
        ):
            session['admin_logged_in'] = True
            session.permanent = True
            flash('Welcome back! 👋', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Invalid username or password.', 'error')
    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('admin_login'))


@app.route('/admin')
@login_required
def admin_dashboard():
    total_products = query_db('SELECT COUNT(*) as cnt FROM products', one=True)['cnt']
    total_orders   = query_db('SELECT COUNT(*) as cnt FROM orders', one=True)['cnt']
    total_revenue  = query_db("SELECT COALESCE(SUM(total),0) as rev FROM orders WHERE status NOT IN ('Cancelled', 'Expired')", one=True)['rev']
    pending_orders = query_db("SELECT COUNT(*) as cnt FROM orders WHERE status = 'Reserved'", one=True)['cnt']
    low_stock      = query_db('SELECT * FROM products WHERE stock <= 2 AND stock > 0 ORDER BY stock ASC')
    out_of_stock   = query_db('SELECT COUNT(*) as cnt FROM products WHERE stock = 0', one=True)['cnt']
    recent_orders  = query_db(
        '''SELECT o.id, o.total, o.status, o.created_at, c.name as customer_name
           FROM orders o JOIN customers c ON o.customer_id = c.id
           ORDER BY o.created_at DESC LIMIT 5'''
    )
    # Monthly revenue – last 6 months (simplified)
    monthly = query_db(
        """SELECT strftime('%Y-%m', created_at) as month, SUM(total) as revenue
           FROM orders WHERE status NOT IN ('Cancelled', 'Expired')
           GROUP BY month ORDER BY month DESC LIMIT 6"""
    )
    return render_template('admin/dashboard.html',
                           total_products=total_products,
                           total_orders=total_orders,
                           total_revenue=total_revenue,
                           pending_orders=pending_orders,
                           low_stock=low_stock,
                           out_of_stock=out_of_stock,
                           recent_orders=recent_orders,
                           monthly=monthly)


# ---- Products ----

@app.route('/admin/products')
@login_required
def admin_products():
    search   = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    q = 'SELECT * FROM products WHERE 1=1'
    args = []
    if search:
        q += ' AND (name LIKE ? OR description LIKE ?)'
        args += [f'%{search}%', f'%{search}%']
    if category:
        q += ' AND category = ?'
        args.append(category)
    q += ' ORDER BY created_at DESC'
    products = query_db(q, args)
    categories = [row['category'] for row in
                  query_db('SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != "" ORDER BY category')]
    return render_template('admin/products.html',
                           products=products,
                           categories=categories,
                           search=search,
                           active_category=category)


@app.route('/admin/purchases')
@login_required
def admin_purchases():
    search   = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    q = 'SELECT * FROM products WHERE 1=1'
    args = []
    if search:
        q += ' AND (name LIKE ? OR description LIKE ?)'
        args += [f'%{search}%', f'%{search}%']
    if category:
        q += ' AND category = ?'
        args.append(category)
    q += ' ORDER BY name ASC'
    products = query_db(q, args)
    categories = [row['category'] for row in
                  query_db('SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != "" ORDER BY category')]
    return render_template('admin/purchases.html',
                           products=products,
                           categories=categories,
                           search=search,
                           active_category=category)


@app.route('/api/admin/products/<int:product_id>/sales')
@login_required
def api_product_sales(product_id):
    sales = query_db(
        '''SELECT o.id as order_id, o.created_at, o.status, c.name as customer_name, c.phone, oi.quantity
           FROM order_items oi
           JOIN orders o ON oi.order_id = o.id
           JOIN customers c ON o.customer_id = c.id
           WHERE oi.product_id = ?
           ORDER BY o.created_at DESC''', [product_id]
    )
    sales_list = []
    for sale in sales:
        sales_list.append({
            'order_id': sale['order_id'],
            'customer_name': sale['customer_name'],
            'phone': sale['phone'],
            'quantity': sale['quantity'],
            'status': sale['status'],
            'created_at': to_ist_filter(sale['created_at'])
        })
    return jsonify(sales_list)


@app.route('/admin/products/add', methods=['GET', 'POST'])
@login_required
def admin_add_product():
    categories = [row['category'] for row in
                  query_db('SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != "" ORDER BY category')]
    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price       = request.form.get('price', '0')
        stock       = request.form.get('stock', '0')
        category    = request.form.get('category', '').strip()
        new_cat     = request.form.get('new_category', '').strip()
        if new_cat:
            category = new_cat

        # Primary Image (Cover)
        image_file = request.files.get('image')
        image_name = save_image(image_file) if image_file and image_file.filename else None

        # Secondary Image (Angle / Detail)
        image2_file = request.files.get('image2')
        image2_name = save_image(image2_file) if image2_file and image2_file.filename else None

        if not name or not price:
            flash('Name and price are required.', 'error')
            return render_template('admin/product_form.html', product=None, categories=categories, action='Add')

        execute_db(
            'INSERT INTO products (name, description, price, stock, image, image2, category) VALUES (?,?,?,?,?,?,?)',
            [name, description, float(price), int(stock), image_name, image2_name, category]
        )
        flash(f'Product "{name}" added successfully! 🎉', 'success')
        return redirect(url_for('admin_products'))

    return render_template('admin/product_form.html', product=None, categories=categories, action='Add')


@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_product(product_id):
    product = query_db('SELECT * FROM products WHERE id = ?', [product_id], one=True)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('admin_products'))
    categories = [row['category'] for row in
                  query_db('SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != "" ORDER BY category')]
    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price       = request.form.get('price', '0')
        stock       = request.form.get('stock', '0')
        category    = request.form.get('category', '').strip()
        new_cat     = request.form.get('new_category', '').strip()
        if new_cat:
            category = new_cat

        # Primary Image (Cover)
        image_file = request.files.get('image')
        image_name = product['image']  # keep existing
        remove_image1 = request.form.get('remove_image1') == '1'
        if remove_image1:
            if image_name:
                old_path = os.path.join(UPLOAD_FOLDER, image_name)
                if os.path.exists(old_path):
                    os.remove(old_path)
            image_name = None
        elif image_file and image_file.filename:
            new_img = save_image(image_file)
            if new_img:
                if image_name:
                    old_path = os.path.join(UPLOAD_FOLDER, image_name)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                image_name = new_img

        # Secondary Image (Angle / Detail)
        image2_file = request.files.get('image2')
        image2_name = product['image2'] if 'image2' in product.keys() else None
        remove_image2 = request.form.get('remove_image2') == '1'
        if remove_image2:
            if image2_name:
                old_path = os.path.join(UPLOAD_FOLDER, image2_name)
                if os.path.exists(old_path):
                    os.remove(old_path)
            image2_name = None
        elif image2_file and image2_file.filename:
            new_img2 = save_image(image2_file)
            if new_img2:
                if image2_name:
                    old_path = os.path.join(UPLOAD_FOLDER, image2_name)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                image2_name = new_img2

        execute_db(
            'UPDATE products SET name=?, description=?, price=?, stock=?, image=?, image2=?, category=? WHERE id=?',
            [name, description, float(price), int(stock), image_name, image2_name, category, product_id]
        )
        flash(f'Product "{name}" updated successfully! ✅', 'success')
        return redirect(url_for('admin_products'))

    return render_template('admin/product_form.html', product=product, categories=categories, action='Edit')


@app.route('/admin/products/delete/<int:product_id>', methods=['POST'])
@login_required
def admin_delete_product(product_id):
    product = query_db('SELECT * FROM products WHERE id = ?', [product_id], one=True)
    if product:
        if product['image']:
            img_path = os.path.join(UPLOAD_FOLDER, product['image'])
            if os.path.exists(img_path):
                os.remove(img_path)
        if 'image2' in product.keys() and product['image2']:
            img2_path = os.path.join(UPLOAD_FOLDER, product['image2'])
            if os.path.exists(img2_path):
                os.remove(img2_path)
        execute_db('DELETE FROM products WHERE id = ?', [product_id])
        flash(f'Product "{product["name"]}" deleted.', 'success')
    return redirect(url_for('admin_products'))


# ---- Orders ----

@app.route('/admin/orders')
@login_required
def admin_orders():
    status_filter = request.args.get('status', '').strip()
    search_query = request.args.get('q', '').strip()
    date_filter = request.args.get('date_filter', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    q = '''SELECT o.id, o.total, o.status, o.created_at,
                  c.name as customer_name, c.phone
           FROM orders o JOIN customers c ON o.customer_id = c.id
           WHERE 1=1'''
    args = []

    # 1. Search Query (Order ID, Customer Name, Phone)
    if search_query:
        clean_search = search_query.lstrip('#')
        search_pattern = f'%{clean_search}%'
        if clean_search.isdigit():
            q += ' AND (o.id = ? OR LOWER(c.name) LIKE LOWER(?) OR LOWER(c.phone) LIKE LOWER(?))'
            args.extend([int(clean_search), search_pattern, search_pattern])
        else:
            q += ' AND (LOWER(c.name) LIKE LOWER(?) OR LOWER(c.phone) LIKE LOWER(?))'
            args.extend([search_pattern, search_pattern])

    # 2. Status Filter
    if status_filter:
        q += ' AND o.status = ?'
        args.append(status_filter)

    # 3. Date Range Filter (based on IST date)
    now_utc = datetime.utcnow()
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    today_ist = now_ist.strftime('%Y-%m-%d')
    yesterday_ist = (now_ist - timedelta(days=1)).strftime('%Y-%m-%d')
    seven_days_ago_ist = (now_ist - timedelta(days=6)).strftime('%Y-%m-%d')

    if date_filter == 'today':
        q += " AND date(o.created_at, '+5 hours', '30 minutes') = ?"
        args.append(today_ist)
    elif date_filter == 'yesterday':
        q += " AND date(o.created_at, '+5 hours', '30 minutes') = ?"
        args.append(yesterday_ist)
    elif date_filter == 'week':
        q += " AND date(o.created_at, '+5 hours', '30 minutes') BETWEEN ? AND ?"
        args.extend([seven_days_ago_ist, today_ist])
    elif date_filter == 'custom':
        if start_date:
            q += " AND date(o.created_at, '+5 hours', '30 minutes') >= ?"
            args.append(start_date)
        if end_date:
            q += " AND date(o.created_at, '+5 hours', '30 minutes') <= ?"
            args.append(end_date)

    q += ' ORDER BY o.created_at DESC'
    orders = query_db(q, args)

    return render_template('admin/orders.html',
                           orders=orders,
                           status_filter=status_filter,
                           search_query=search_query,
                           date_filter=date_filter,
                           start_date=start_date,
                           end_date=end_date)



@app.route('/admin/orders/<int:order_id>')
@login_required
def admin_order_detail(order_id):
    order = query_db(
        '''SELECT o.*, c.name as customer_name, c.phone, c.whatsapp, c.address, c.pincode, c.post_office, c.district
           FROM orders o JOIN customers c ON o.customer_id = c.id
           WHERE o.id = ?''', [order_id], one=True
    )
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('admin_orders'))
    items = query_db(
        '''SELECT oi.quantity, oi.price, p.name as product_name, p.image
           FROM order_items oi LEFT JOIN products p ON oi.product_id = p.id
           WHERE oi.order_id = ?''', [order_id]
    )
    return render_template('admin/order_detail.html', order=order, items=items)


@app.route('/admin/orders/<int:order_id>/status', methods=['POST'])
@login_required
def admin_update_order_status(order_id):
    new_status = request.form.get('status', 'Pending')
    
    db = get_db()
    # Get current status
    order = query_db('SELECT status FROM orders WHERE id = ?', [order_id], one=True)
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('admin_orders'))
        
    old_status = order['status']
    
    # Active statuses that reserve stock
    active_statuses = {'Pending', 'Confirmed', 'Shipped', 'Reserved'}
    inactive_statuses = {'Cancelled', 'Expired'}
    
    # Get stock reduction mode setting
    stock_mode = get_setting('stock_reduction_mode', 'reserve')
    
    if stock_mode == 'reserve':
        # Transition: Active -> Inactive (release stock)
        if old_status in active_statuses and new_status in inactive_statuses:
            items = query_db('SELECT product_id, quantity FROM order_items WHERE order_id = ?', [order_id])
            for item in items:
                db.execute('UPDATE products SET stock = stock + ? WHERE id = ?', [item['quantity'], item['product_id']])
            db.commit()
            flash(f'Order #{order_id} marked as {new_status}. Stock restored to inventory. 🔄', 'info')
            
        # Transition: Inactive -> Active (re-reserve stock)
        elif old_status in inactive_statuses and new_status in active_statuses:
            items = query_db('SELECT product_id, quantity FROM order_items WHERE order_id = ?', [order_id])
            for item in items:
                db.execute('UPDATE products SET stock = stock - ? WHERE id = ?', [item['quantity'], item['product_id']])
            db.commit()
            flash(f'Order #{order_id} re-activated. Stock reserved from inventory. 📦', 'info')

    # If the order is confirmed, shipped, or cancelled, clear the reservation timer
    if new_status != 'Reserved':
        execute_db('UPDATE orders SET reserved_until = NULL WHERE id = ?', [order_id])

    # Update status
    execute_db('UPDATE orders SET status = ? WHERE id = ?', [new_status, order_id])
    flash(f'Order #{order_id} status updated to {new_status}.', 'success')
    return redirect(url_for('admin_order_detail', order_id=order_id))


# ---- Settings ----

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    if request.method == 'POST':
        shop_name  = request.form.get('shop_name', '').strip()
        whatsapp   = request.form.get('whatsapp_number', '').strip()
        currency_s = request.form.get('currency_symbol', '₹').strip()
        currency_c = request.form.get('currency_code', 'INR').strip()
        new_user   = request.form.get('admin_username', '').strip()
        new_pass   = request.form.get('admin_password', '').strip()
        confirm    = request.form.get('confirm_password', '').strip()
        # Checkbox: present = '1' (show), absent = '0' (hide)
        show_oos   = '1' if request.form.get('show_out_of_stock') else '0'
        stock_mode = request.form.get('stock_reduction_mode', 'reserve')
        res_mins   = request.form.get('reservation_minutes', '15').strip()
        store_notice = request.form.get('store_notice', '').strip()

        if shop_name:
            set_setting('shop_name', shop_name)
        if whatsapp:
            set_setting('whatsapp_number', whatsapp)
        set_setting('currency_symbol', currency_s)
        set_setting('currency_code', currency_c)
        set_setting('show_out_of_stock', show_oos)
        set_setting('stock_reduction_mode', stock_mode)
        set_setting('reservation_minutes', res_mins)
        set_setting('store_notice', store_notice)

        # Shop Logo Upload & Removal
        remove_logo = request.form.get('remove_logo') == '1'
        logo_file = request.files.get('shop_logo')

        if remove_logo:
            old_logo = get_setting('shop_logo', '')
            if old_logo:
                old_path = os.path.join(UPLOAD_FOLDER, old_logo)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
            set_setting('shop_logo', '')
        elif logo_file and logo_file.filename:
            new_logo = save_logo_image(logo_file)
            if new_logo:
                old_logo = get_setting('shop_logo', '')
                if old_logo and old_logo != new_logo:
                    old_path = os.path.join(UPLOAD_FOLDER, old_logo)
                    if os.path.exists(old_path):
                        try:
                            os.remove(old_path)
                        except OSError:
                            pass
                set_setting('shop_logo', new_logo)

        maintenance_mode = '1' if request.form.get('maintenance_mode') else '0'
        maintenance_msg  = request.form.get('maintenance_message', '').strip()
        set_setting('maintenance_mode', maintenance_mode)
        set_setting('maintenance_message', maintenance_msg or 'We are currently updating our stock. Kindly visit later!')
        if new_user:
            set_setting('admin_username', new_user)
            session['admin_username'] = new_user
        if new_pass:
            if new_pass != confirm:
                flash('Passwords do not match.', 'error')
                return redirect(url_for('admin_settings'))
            set_setting('admin_password', hash_password(new_pass))
            flash('Password updated. Please log in again.', 'info')
            session.clear()
            return redirect(url_for('admin_login'))

        flash('Settings saved successfully! ✅', 'success')
        return redirect(url_for('admin_settings'))

    return render_template('admin/settings.html')


@app.route('/admin/clear-data', methods=['POST'])
@login_required
def admin_clear_data():
    clear_type = request.form.get('clear_type', '')
    db = get_db()

    if clear_type == 'orders':
        db.execute('DELETE FROM order_items')
        db.execute('DELETE FROM orders')
        db.commit()
        flash('All orders and order items have been deleted. 🗑️', 'success')

    elif clear_type == 'customers':
        # Cascades to orders and order_items via FK ON DELETE CASCADE
        db.execute('DELETE FROM order_items')
        db.execute('DELETE FROM orders')
        db.execute('DELETE FROM customers')
        db.commit()
        flash('All customers, orders, and order items have been deleted. 🗑️', 'success')

    elif clear_type == 'all':
        db.execute('DELETE FROM order_items')
        db.execute('DELETE FROM orders')
        db.execute('DELETE FROM customers')
        db.commit()
        flash('All data cleared — orders, order items, and customers deleted. 🗑️', 'success')

    else:
        flash('Unknown clear type.', 'error')

    return redirect(url_for('admin_settings'))


# ===========================================================================
# Entry Point
# ===========================================================================

# Always run DB setup (works under both WSGI and direct python app.py)
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)

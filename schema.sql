-- Database schema for Small Shop Online Store Platform

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS settings;

-- Store dynamic configurations
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Products table
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    price REAL NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    image TEXT, -- Stores the filename in /static/uploads
    category TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Customers table
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    whatsapp TEXT NOT NULL,
    address TEXT NOT NULL,
    pincode TEXT NOT NULL
);

-- Orders table
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending', -- Pending, Confirmed, Shipped, Cancelled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

-- Order Items table
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL, -- Price at the time of purchase
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
);

-- Seed dynamic settings
INSERT INTO settings (key, value) VALUES ('shop_name', 'The Cozy Corner');
INSERT INTO settings (key, value) VALUES ('whatsapp_number', '919876543210');
INSERT INTO settings (key, value) VALUES ('admin_username', 'admin');
INSERT INTO settings (key, value) VALUES ('admin_password', 'admin123'); -- Will be hashed on first run by app.py
INSERT INTO settings (key, value) VALUES ('currency_symbol', '₹');
INSERT INTO settings (key, value) VALUES ('currency_code', 'INR');

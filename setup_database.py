import sqlite3
import os

def create_database(db_name="database.db"):
    """
    Creates a new, empty SQLite database with the required schema for the Cabinet Estimator app.
    If a database with the same name already exists, it will be overwritten.
    """
    
    # Check if the database file exists and remove it to ensure a fresh start.
    if os.path.exists(db_name):
        os.remove(db_name)
        print(f"Removed existing database '{db_name}'.")

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    # --- Create Tables ---

    # Categories Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        sort_order INTEGER
    )
    """)
    print("Created 'categories' table.")

    # Customers Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        phone TEXT,
        email TEXT
    )
    """)
    print("Created 'customers' table.")

    # Price List Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pricelist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT NOT NULL,
        unit_price REAL NOT NULL,
        sort_order INTEGER,
        category_id INTEGER,
        FOREIGN KEY (category_id) REFERENCES categories (id)
    )
    """)
    print("Created 'pricelist' table.")

    # Estimate Jobs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS estimate_jobs (
        job_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        job_name TEXT,
        estimate_date TEXT,
        total_amount REAL,
        install_total REAL,
        markup_percent REAL,
        misc_charge REAL,
        FOREIGN KEY (customer_id) REFERENCES customers (id)
    )
    """)
    print("Created 'estimate_jobs' table.")

    # Estimate Line Items Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS estimate_line_items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        item_name TEXT,
        category_name TEXT,
        quantity INTEGER,
        unit_price REAL,
        line_total REAL,
        FOREIGN KEY (job_id) REFERENCES estimate_jobs (job_id)
    )
    """)
    print("Created 'estimate_line_items' table.")

    # --- Add Default Data ---

    # Add the default 'Uncategorized' category, which is required by the app.
    try:
        cursor.execute("INSERT INTO categories (name, sort_order) VALUES ('Uncategorized', 0)")
        print("Added default 'Uncategorized' category.")
    except sqlite3.IntegrityError:
        print("'Uncategorized' category already exists.")
    
    conn.commit()
    conn.close()
    
    print("\nDatabase setup complete. The file 'database.db' is ready to use.")

if __name__ == "__main__":
    create_database()

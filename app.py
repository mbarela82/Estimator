# app.py
import customtkinter as ctk
import sqlite3
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from datetime import datetime
import os
import platform
import subprocess
import sys
import tempfile
import fitz  # PyMuPDF
from PIL import Image
import tkinter
import tkinter.filedialog
import shutil
import csv
from CTkToolTip import CTkToolTip

def resource_path(relative_path):
    """ Get absolute path to read-only resources, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- MODIFICATION START ---
def get_app_data_path():
    """Gets the path to a writable application data directory for the database."""
    home = os.path.expanduser("~")
    app_data_dir = os.path.join(home, ".CC-Estimator")
    os.makedirs(app_data_dir, exist_ok=True) # Ensure the directory exists
    return app_data_dir

def db_connect():
    """Connects to the database in the user's writable app data folder."""
    db_path = os.path.join(get_app_data_path(), 'database.db')
    return sqlite3.connect(db_path)
# --- MODIFICATION END ---


# --- NEW: Helper function for database migration ---
def _add_column_if_not_exists(cursor, table_name, column_name, column_type):
    """Adds a column to a table if it doesn't already exist."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [info[1] for info in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

def setup_database():
    """Ensures all necessary tables exist and migrates old schemas."""
    conn = db_connect()
    cursor = conn.cursor()
    # Create main tables if they don't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT, phone TEXT, email TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, sort_order INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pricelist (
            id INTEGER PRIMARY KEY, item_name TEXT NOT NULL, unit_price REAL NOT NULL, sort_order INTEGER,
            category_id INTEGER, FOREIGN KEY (category_id) REFERENCES categories(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estimate_jobs (
            job_id INTEGER PRIMARY KEY, customer_id INTEGER, job_name TEXT, estimate_date TEXT, total_amount REAL,
            install_total REAL, markup_percent REAL, misc_charge REAL,
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estimate_line_items (
            item_id INTEGER PRIMARY KEY, job_id INTEGER, item_name TEXT, category_name TEXT, quantity INTEGER,
            unit_price REAL, line_total REAL,
            FOREIGN KEY (job_id) REFERENCES estimate_jobs (job_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        )
    """)
    
    # Ensure 'Uncategorized' category exists
    cursor.execute("INSERT OR IGNORE INTO categories (name, sort_order) VALUES ('Uncategorized', 9999)")
    
    # Add columns for saving individual install qty and price (schema migration)
    _add_column_if_not_exists(cursor, "estimate_jobs", "install_qty", "REAL")
    _add_column_if_not_exists(cursor, "estimate_jobs", "install_unit_price", "REAL")
    
    conn.commit()
    conn.close()

def save_setting(key, value):
    """Saves a setting to the database."""
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def load_setting(key, default_value=None):
    """Loads a setting from the database."""
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else default_value

class CustomMessageBox(ctk.CTkToplevel):
    def __init__(self, master=None, title="Dialog", message="Message", buttons=["OK"]):
        super().__init__(master)
        self.title(title); self.geometry("450x170"); self.lift(); self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.cancel); self.grab_set(); self.resizable(False, False)
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1); self._result = None
        self._message_label = ctk.CTkLabel(self, text=message, wraplength=410); self._message_label.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self._button_frame = ctk.CTkFrame(self, fg_color="transparent"); self._button_frame.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="s")
        if "Yes" in buttons and "No" in buttons:
            yes_button = ctk.CTkButton(self._button_frame, text="Yes", command=self.yes); yes_button.pack(side="left", padx=(0, 10))
            no_button = ctk.CTkButton(self._button_frame, text="No", command=self.no, fg_color="#D32F2F", hover_color="#C62828"); no_button.pack(side="left")
        else:
            ok_button = ctk.CTkButton(self._button_frame, text="OK", command=self.ok); ok_button.pack()
        if master:
            self.after(10, self.center_window)
    def center_window(self):
        try:
            self.update_idletasks()
            master = self.master
            if master.winfo_viewable():
                main_x = master.winfo_x(); main_y = master.winfo_y(); main_width = master.winfo_width(); main_height = master.winfo_height()
                win_width = self.winfo_width(); win_height = self.winfo_height(); x = main_x + (main_width // 2) - (win_width // 2); y = main_y + (main_height // 2) - (win_height // 2); self.geometry(f'+{x}+{y}')
        except Exception:
            self.geometry("450x170")
    def yes(self): self._result = True; self.destroy()
    def no(self): self._result = False; self.destroy()
    def ok(self): self._result = True; self.destroy()
    def cancel(self): self._result = False; self.destroy()
    def get_result(self): self.master.wait_window(self); return self._result

class PDFViewerWindow(ctk.CTkToplevel):
    def __init__(self, master, pdf_path):
        super().__init__(master)
        self.pdf_path = pdf_path
        self.title("Estimate Preview")
        self.geometry("850x900")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1)
        self.scroll_frame = ctk.CTkScrollableFrame(self, label_text="PDF Preview"); self.scroll_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent"); self.button_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="e")
        self.print_button = ctk.CTkButton(self.button_frame, text="Print", width=120, command=self.print_pdf); self.print_button.pack(side="right", padx=(10, 0))
        self.save_button = ctk.CTkButton(self.button_frame, text="Save as PDF", width=120, command=self.save_pdf); self.save_button.pack(side="right")
        self.after(100, self.display_pdf)
    def display_pdf(self):
        target_width = self.scroll_frame.winfo_width() - 40
        try:
            doc = fitz.open(self.pdf_path)
            for page_num in range(len(doc)):
                page = doc.load_page(page_num); zoom_factor = target_width / page.rect.width; matrix = fitz.Matrix(zoom_factor, zoom_factor); pix = page.get_pixmap(matrix=matrix)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples); ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(pix.width, pix.height))
                label = ctk.CTkLabel(self.scroll_frame, image=ctk_img, text=""); label.pack(pady=10, padx=10)
            doc.close()
        except Exception as e:
            error_label = ctk.CTkLabel(self.scroll_frame, text=f"Error rendering PDF: {e}"); error_label.pack(pady=20, padx=20)
    def save_pdf(self):
        file_path = tkinter.filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF Documents", "*.pdf")], title="Save Estimate As...", initialfile=f"Estimate_{datetime.now().strftime('%Y-%m-%d')}.pdf")
        if file_path:
            try:
                shutil.copy(self.pdf_path, file_path); CustomMessageBox(self, title="Success", message=f"PDF saved to:\n{file_path}").get_result()
            except Exception as e:
                CustomMessageBox(self, title="Error", message=f"Could not save file: {e}").get_result()
    def print_pdf(self):
        try:
            current_os = platform.system()
            if current_os == "Windows": os.startfile(self.pdf_path, "print")
            elif current_os == "Darwin": subprocess.call(["lpr", self.pdf_path])
            elif current_os == "Linux": subprocess.call(["lp", self.pdf_path])
            else: CustomMessageBox(self, title="Print Error", message="Unsupported OS for printing.").get_result()
        except Exception as e:
            CustomMessageBox(self, title="Print Error", message=f"Failed to open print dialog:\n{e}").get_result()
    def on_close(self):
        if self.pdf_path and os.path.exists(self.pdf_path):
            try: os.remove(self.pdf_path)
            except OSError as e: print(f"Error deleting temp file: {e}")
        self.destroy()

class CategoryManagerWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master); self.editing_category_id = None; self.title("Category Manager"); self.geometry("400x400"); self.grab_set()
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1)
        self.display_frame = ctk.CTkScrollableFrame(self, label_text="Categories"); self.display_frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        add_frame = ctk.CTkFrame(self); add_frame.grid(row=1, column=0, padx=20, pady=(0,20), sticky="ew"); add_frame.grid_columnconfigure(0, weight=1)
        self.name_entry = ctk.CTkEntry(add_frame, placeholder_text="Category Name"); self.name_entry.grid(row=0, column=0, padx=(0,10), sticky="ew")
        self.add_button = ctk.CTkButton(add_frame, text="Add New", width=80, command=self.add_or_update_category); self.add_button.grid(row=0, column=1); self.refresh_list()
    def refresh_list(self):
        for widget in self.display_frame.winfo_children(): widget.destroy()
        conn = db_connect(); cursor = conn.cursor(); cursor.execute("SELECT id, name FROM categories ORDER BY sort_order ASC"); categories = cursor.fetchall(); conn.close()
        for index, (cat_id, name) in enumerate(categories):
            row_frame = ctk.CTkFrame(self.display_frame); row_frame.pack(fill="x", padx=5, pady=4); label = ctk.CTkLabel(row_frame, text=name, anchor="w"); label.pack(side="left", fill="x", expand=True, padx=5)
            if name != "Uncategorized":
                down_button = ctk.CTkButton(row_frame, text="▼", width=30, command=lambda i=cat_id: self.move_category(i, 'down')); down_button.pack(side="right", padx=(5,0))
                if index == len(categories) - 1: down_button.configure(state="disabled")
                up_button = ctk.CTkButton(row_frame, text="▲", width=30, command=lambda i=cat_id: self.move_category(i, 'up')); up_button.pack(side="right", padx=5)
                if index == 0: up_button.configure(state="disabled")
                delete_btn = ctk.CTkButton(row_frame, text="Delete", width=60, fg_color="#D32F2F", hover_color="#C62828", command=lambda i=cat_id: self.delete_category(i)); delete_btn.pack(side="right", padx=5)
                edit_btn = ctk.CTkButton(row_frame, text="Edit", width=50, command=lambda i=cat_id, n=name: self.populate_edit_fields(i, n)); edit_btn.pack(side="right", padx=5)
    def populate_edit_fields(self, cat_id, name):
        self.editing_category_id = cat_id; self.name_entry.delete(0, 'end'); self.name_entry.insert(0, name); self.add_button.configure(text="Update")
    def add_or_update_category(self):
        name = self.name_entry.get().strip();
        if not name: return
        conn = db_connect(); cursor = conn.cursor()
        try:
            if self.editing_category_id: cursor.execute("UPDATE categories SET name = ? WHERE id = ?", (name, self.editing_category_id))
            else:
                cursor.execute("SELECT MAX(sort_order) FROM categories"); max_order = cursor.fetchone()[0] or 0
                cursor.execute("INSERT INTO categories (name, sort_order) VALUES (?, ?)", (name, max_order + 1))
            conn.commit(); self.name_entry.delete(0, 'end'); self.editing_category_id = None; self.add_button.configure(text="Add New")
        except sqlite3.IntegrityError: CustomMessageBox(self, title="Error", message=f"Category '{name}' already exists.").get_result()
        finally: conn.close(); self.refresh_list()
    def delete_category(self, cat_id):
        confirm_delete = True
        if load_setting('show_confirmations', 'True') == 'True':
            dialog = CustomMessageBox(self, title="Confirm Delete", message="Are you sure? Items in this category will be moved to 'Uncategorized'.", buttons=["Yes", "No"])
            confirm_delete = dialog.get_result()
        if confirm_delete:
            conn = db_connect(); cursor = conn.cursor(); cursor.execute("SELECT id FROM categories WHERE name='Uncategorized'"); uncategorized_id = cursor.fetchone()[0]
            cursor.execute("UPDATE pricelist SET category_id = ? WHERE category_id = ?", (uncategorized_id, cat_id)); cursor.execute("DELETE FROM categories WHERE id = ?", (cat_id,)); conn.commit(); conn.close(); self.refresh_list()
    def move_category(self, cat_id, direction):
        conn = db_connect(); cursor = conn.cursor(); cursor.execute("SELECT id, sort_order FROM categories ORDER BY sort_order"); sorted_items = cursor.fetchall(); item_index = -1
        for i, (i_id, so) in enumerate(sorted_items):
            if i_id == cat_id: item_index = i; break
        if item_index == -1: conn.close(); return
        if direction == 'up' and item_index > 0: other_index = item_index - 1
        elif direction == 'down' and item_index < len(sorted_items) - 1: other_index = item_index + 1
        else: conn.close(); return
        item1_id, item1_so = sorted_items[item_index]; item2_id, item2_so = sorted_items[other_index]
        cursor.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (item2_so, item1_id)); cursor.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (item1_so, item2_id)); conn.commit(); conn.close(); self.refresh_list()

class CustomerManagerWindow(ctk.CTkToplevel):
    def __init__(self, master, estimate_frame):
        super().__init__(master); self.estimate_frame = estimate_frame; self.editing_customer_id = None; self.title("Customer Manager"); self.geometry("700x550"); self.grab_set(); self.after(250, lambda: self.iconbitmap(''))
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(2, weight=1)
        form_frame = ctk.CTkFrame(self); form_frame.grid(row=0, column=0, padx=20, pady=(20,10), sticky="ew"); form_frame.grid_columnconfigure(1, weight=1)
        self.name_entry = ctk.CTkEntry(form_frame, placeholder_text="Full Name"); self.name_entry.grid(row=0, column=0, columnspan=2, padx=10, pady=(10,5), sticky="ew"); self.address_entry = ctk.CTkEntry(form_frame, placeholder_text="Address"); self.address_entry.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        self.phone_entry = ctk.CTkEntry(form_frame, placeholder_text="Phone Number"); self.phone_entry.grid(row=2, column=0, padx=(10,5), pady=5, sticky="ew"); self.email_entry = ctk.CTkEntry(form_frame, placeholder_text="Email"); self.email_entry.grid(row=2, column=1, padx=(5,10), pady=5, sticky="ew")
        self.save_button = ctk.CTkButton(form_frame, text="Add New Customer", command=self.add_or_update_customer); self.save_button.grid(row=3, column=0, columnspan=2, padx=10, pady=10)
        self.search_entry = ctk.CTkEntry(self, placeholder_text="Search"); self.search_entry.grid(row=1, column=0, padx=20, pady=(10,0), sticky="ew"); self.search_entry.bind("<KeyRelease>", self.filter_list)
        self.display_frame = ctk.CTkScrollableFrame(self, label_text="Saved Customers"); self.display_frame.grid(row=2, column=0, padx=20, pady=(10,20), sticky="nsew")
        self.all_customers = []; self.refresh_list()
    def refresh_list(self):
        conn = db_connect(); cursor = conn.cursor(); cursor.execute("SELECT id, name, phone, email, address FROM customers ORDER BY name"); self.all_customers = cursor.fetchall(); conn.close()
        self.display_customers(self.all_customers)
    def filter_list(self, event=None):
        search_term = self.search_entry.get().lower()
        if not search_term: self.display_customers(self.all_customers); return
        filtered_customers = [cust for cust in self.all_customers if search_term in cust[1].lower() or (cust[2] and search_term in cust[2].lower())]
        self.display_customers(filtered_customers)
    def display_customers(self, customer_list):
        for widget in self.display_frame.winfo_children(): widget.destroy()
        for (cust_id, name, phone, email, address) in customer_list:
            row_frame = ctk.CTkFrame(self.display_frame); row_frame.pack(fill="x", padx=5, pady=4)
            label = ctk.CTkLabel(row_frame, text=f"{name}  ({phone or 'No phone'})", anchor="w"); label.pack(side="left", fill="x", expand=True, padx=10)
            delete_btn = ctk.CTkButton(row_frame, text="Delete", width=60, fg_color="#D32F2F", hover_color="#C62828", command=lambda i=cust_id: self.delete_customer(i)); delete_btn.pack(side="right", padx=5)
            edit_btn = ctk.CTkButton(row_frame, text="Edit", width=50, command=lambda c_id=cust_id, n=name, a=address, p=phone, e=email: self.populate_edit_fields(c_id, n, a, p, e)); edit_btn.pack(side="right", padx=5)
    def populate_edit_fields(self, cust_id, name, address, phone, email):
        self.editing_customer_id = cust_id; self.name_entry.delete(0, 'end'); self.name_entry.insert(0, name); self.address_entry.delete(0, 'end'); self.address_entry.insert(0, address or "")
        self.phone_entry.delete(0, 'end'); self.phone_entry.insert(0, phone or ""); self.email_entry.delete(0, 'end'); self.email_entry.insert(0, email or ""); self.save_button.configure(text=f"Update Customer")
    def add_or_update_customer(self):
        name = self.name_entry.get().strip();
        if not name: CustomMessageBox(self, title="Input Error", message="Customer name cannot be empty.").get_result(); return
        address = self.address_entry.get().strip(); phone = self.phone_entry.get().strip(); email = self.email_entry.get().strip()
        conn = db_connect(); cursor = conn.cursor()
        if self.editing_customer_id: cursor.execute("UPDATE customers SET name=?, address=?, phone=?, email=? WHERE id=?", (name, address, phone, email, self.editing_customer_id))
        else: cursor.execute("INSERT INTO customers (name, address, phone, email) VALUES (?, ?, ?, ?)", (name, address, phone, email))
        conn.commit(); conn.close(); self.editing_customer_id = None; self.name_entry.delete(0, 'end'); self.address_entry.delete(0, 'end'); self.phone_entry.delete(0, 'end'); self.email_entry.delete(0, 'end')
        self.save_button.configure(text="Add New Customer"); self.refresh_list(); self.estimate_frame.update_dropdowns()
    def delete_customer(self, cust_id):
        confirm_delete = True
        if load_setting('show_confirmations', 'True') == 'True':
            dialog = CustomMessageBox(self, title="Confirm Delete", message="Are you sure? This will also delete ALL estimates associated with this customer. This action cannot be undone.", buttons=["Yes", "No"])
            confirm_delete = dialog.get_result()
        if confirm_delete:
            conn = db_connect(); cursor = conn.cursor()
            cursor.execute("DELETE FROM estimate_jobs WHERE customer_id = ?", (cust_id,)); cursor.execute("DELETE FROM customers WHERE id = ?", (cust_id,)); conn.commit(); conn.close()
            self.refresh_list(); self.estimate_frame.update_dropdowns()

class PriceListWindow(ctk.CTkToplevel):
    def __init__(self, master, estimate_frame):
        super().__init__(master)
        self.estimate_frame = estimate_frame; self.editing_item_id = None; self.title("Price List Manager"); self.geometry("700x600"); self.grab_set(); self.after(250, lambda: self.iconbitmap(''))
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(3, weight=1); self.categories = {}; self.items_by_cat = {}; self.all_items_from_db = []
        top_frame = ctk.CTkFrame(self, fg_color="transparent"); top_frame.grid(row=0, column=0, padx=20, pady=(20,0), sticky="ew")
        self.manage_categories_button = ctk.CTkButton(top_frame, text="Manage Categories", command=self.open_category_manager); self.manage_categories_button.pack(side="right")
        self.form_frame = ctk.CTkFrame(self); self.form_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew"); self.form_frame.grid_columnconfigure(0, weight=1)
        self.item_name_entry = ctk.CTkEntry(self.form_frame, placeholder_text="Item Name"); self.item_name_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.unit_price_entry = ctk.CTkEntry(self.form_frame, placeholder_text="Unit Price ($)", width=120); self.unit_price_entry.grid(row=0, column=1, padx=10, pady=10)
        self.category_menu = ctk.CTkOptionMenu(self.form_frame, values=["-"]); self.category_menu.grid(row=0, column=2, padx=10, pady=10)
        self.add_button = ctk.CTkButton(self.form_frame, text="Add New Item", command=self.add_or_update_item); self.add_button.grid(row=0, column=3, padx=10, pady=10)
        search_and_select_frame = ctk.CTkFrame(self); search_and_select_frame.grid(row=2, column=0, padx=20, pady=(10, 0), sticky="ew"); search_and_select_frame.grid_columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(search_and_select_frame, placeholder_text="Search"); self.search_entry.grid(row=0, column=0, padx=(0, 10), pady=5, sticky="ew"); self.search_entry.bind("<KeyRelease>", self.on_search)
        self.category_selector = ctk.CTkOptionMenu(search_and_select_frame, command=self.display_items_for_category, values=["-"]); self.category_selector.grid(row=0, column=1, padx=(0,0), pady=5)
        self.item_display_frame = ctk.CTkScrollableFrame(self); self.item_display_frame.grid(row=3, column=0, padx=20, pady=(10, 20), sticky="nsew")
        self.refresh_data_and_ui()
    def on_search(self, event=None):
        search_term = self.search_entry.get().lower();
        for widget in self.item_display_frame.winfo_children(): widget.destroy()
        if not search_term:
            self.category_selector.configure(state="normal"); self.display_items_for_category(self.category_selector.get()); return
        self.category_selector.configure(state="disabled"); filtered_items = [item for item in self.all_items_from_db if search_term in item[1].lower()]
        for item_id, name, price, item_cat_id, cat_name in filtered_items:
            row_frame = ctk.CTkFrame(self.item_display_frame); row_frame.pack(fill="x", padx=5, pady=2)
            label = ctk.CTkLabel(row_frame, text=f"[{cat_name}] {name}: ${price:.2f}", anchor="w"); label.pack(side="left", fill="x", expand=True, padx=5, pady=2)
            down_button = ctk.CTkButton(row_frame, text="▼", width=30, state="disabled"); down_button.pack(side="right", padx=(5,0))
            up_button = ctk.CTkButton(row_frame, text="▲", width=30, state="disabled"); up_button.pack(side="right", padx=5)
            delete_button = ctk.CTkButton(row_frame, text="Delete", width=60, fg_color="#D32F2F", hover_color="#C62828", command=lambda i=item_id: self.delete_item(i)); delete_button.pack(side="right", padx=5)
            edit_button = ctk.CTkButton(row_frame, text="Edit", width=50, command=lambda i=item_id, n=name, p=price, cn=cat_name: self.populate_edit_fields(i, n, p, cn)); edit_button.pack(side="right", padx=5)
    def open_category_manager(self):
        cat_manager = CategoryManagerWindow(self); self.wait_window(cat_manager); self.refresh_data_and_ui(); self.estimate_frame.update_dropdowns()
    def add_or_update_item(self):
        name = self.item_name_entry.get().strip(); price_str = self.unit_price_entry.get(); cat_name = self.category_menu.get()
        if not name or not price_str or cat_name == "-": return
        try: price = float(price_str)
        except ValueError: CustomMessageBox(self, title="Invalid Input", message="Please enter a valid number for the price.").get_result(); return
        cat_id = self.categories.get(cat_name); conn = db_connect(); cursor = conn.cursor()
        if self.editing_item_id is not None:
            cursor.execute("UPDATE pricelist SET item_name = ?, unit_price = ?, category_id = ? WHERE id = ?", (name, price, cat_id, self.editing_item_id))
        else:
            cursor.execute("SELECT MAX(sort_order) FROM pricelist WHERE category_id = ?", (cat_id,)); max_order = cursor.fetchone()[0] or 0
            cursor.execute("INSERT INTO pricelist (item_name, unit_price, sort_order, category_id) VALUES (?, ?, ?, ?)", (name, price, max_order + 1, cat_id))
        conn.commit(); conn.close(); self.item_name_entry.delete(0, 'end'); self.unit_price_entry.delete(0, 'end'); self.editing_item_id = None; self.add_button.configure(text="Add New Item")
        self.refresh_data_and_ui(select_category=cat_name); self.estimate_frame.update_dropdowns()
    def refresh_data_and_ui(self, select_category=None):
        self.category_selector.configure(state="normal")
        if select_category is None:
            try:
                current_selection = self.category_selector.get()
                if current_selection != "-": select_category = current_selection
            except Exception: pass
        conn = db_connect(); cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM categories ORDER BY CASE WHEN name = 'Uncategorized' THEN 1 ELSE 0 END, sort_order")
        db_categories = cursor.fetchall(); self.categories.clear(); cat_options = [] if db_categories else ["-"]
        for cat_id, name in db_categories: self.categories[name] = cat_id; cat_options.append(name)
        query = """SELECT p.id, p.item_name, p.unit_price, p.category_id, c.name FROM pricelist p JOIN categories c ON p.category_id = c.id ORDER BY p.sort_order ASC"""
        cursor.execute(query); self.all_items_from_db = cursor.fetchall(); conn.close()
        self.items_by_cat.clear()
        for cat_id, cat_name in db_categories: self.items_by_cat[cat_name] = []
        for item in self.all_items_from_db:
            cat_name = item[4]
            if cat_name in self.items_by_cat: self.items_by_cat[cat_name].append(item)
        self.category_menu.configure(values=cat_options); self.category_selector.configure(values=cat_options)
        category_to_display = select_category
        if category_to_display not in cat_options: category_to_display = cat_options[0] if cat_options and cat_options[0] != "-" else None
        if category_to_display: self.category_selector.set(category_to_display); self.display_items_for_category(category_to_display)
        else: self.category_selector.set("-"); self.display_items_for_category(None)
    def display_items_for_category(self, category_name):
        for widget in self.item_display_frame.winfo_children(): widget.destroy()
        if category_name is None or category_name not in self.items_by_cat: return
        category_items = self.items_by_cat[category_name]
        for index, (item_id, name, price, item_cat_id, _) in enumerate(category_items):
            row_frame = ctk.CTkFrame(self.item_display_frame); row_frame.pack(fill="x", padx=5, pady=2)
            label = ctk.CTkLabel(row_frame, text=f"{name}: ${price:.2f}", anchor="w"); label.pack(side="left", fill="x", expand=True, padx=5, pady=2)
            down_button = ctk.CTkButton(row_frame, text="▼", width=30, command=lambda i=item_id, c=item_cat_id: self.move_item(i, 'down', c)); down_button.pack(side="right", padx=(5,0))
            if index == len(category_items) - 1: down_button.configure(state="disabled")
            up_button = ctk.CTkButton(row_frame, text="▲", width=30, command=lambda i=item_id, c=item_cat_id: self.move_item(i, 'up', c)); up_button.pack(side="right", padx=5)
            if index == 0: up_button.configure(state="disabled")
            delete_button = ctk.CTkButton(row_frame, text="Delete", width=60, fg_color="#D32F2F", hover_color="#C62828", command=lambda i=item_id: self.delete_item(i)); delete_button.pack(side="right", padx=5)
            edit_button = ctk.CTkButton(row_frame, text="Edit", width=50, command=lambda i=item_id, n=name, p=price, cn=category_name: self.populate_edit_fields(i, n, p, cn)); edit_button.pack(side="right", padx=5)
    def move_item(self, item_id, direction, category_id):
        conn = db_connect(); cursor = conn.cursor()
        cursor.execute("SELECT id, sort_order FROM pricelist WHERE category_id = ? ORDER BY sort_order", (category_id,)); sorted_items = cursor.fetchall(); item_index = -1
        for i, (i_id, so) in enumerate(sorted_items):
            if i_id == item_id: item_index = i; break
        if item_index == -1: conn.close(); return
        if direction == 'up' and item_index > 0: other_index = item_index - 1
        elif direction == 'down' and item_index < len(sorted_items) - 1: other_index = item_index + 1
        else: conn.close(); return
        item1_id, item1_so = sorted_items[item_index]; item2_id, item2_so = sorted_items[other_index]
        cursor.execute("UPDATE pricelist SET sort_order = ? WHERE id = ?", (item2_so, item1_id)); cursor.execute("UPDATE pricelist SET sort_order = ? WHERE id = ?", (item1_so, item2_id)); conn.commit(); conn.close()
        cat_id_to_name = {v: k for k, v in self.categories.items()}; cat_name = cat_id_to_name.get(category_id)
        self.refresh_data_and_ui(select_category=cat_name); self.estimate_frame.update_dropdowns()
    def populate_edit_fields(self, item_id, name, price, cat_name):
        self.editing_item_id = item_id; self.item_name_entry.delete(0, 'end'); self.unit_price_entry.delete(0, 'end')
        self.item_name_entry.insert(0, name); 
        if price == int(price):
            self.unit_price_entry.insert(0, str(int(price)))
        else:
            self.unit_price_entry.insert(0, str(price))
        self.category_menu.set(cat_name); self.add_button.configure(text="Update Item")
    def delete_item(self, item_id):
        confirm_delete = True
        if load_setting('show_confirmations', 'True') == 'True':
            dialog = CustomMessageBox(self, title="Confirm Delete", message=f"Are you sure you want to delete this item?", buttons=["Yes", "No"])
            confirm_delete = dialog.get_result()
        if confirm_delete:
            conn = db_connect(); cursor = conn.cursor()
            cursor.execute("DELETE FROM pricelist WHERE id = ?", (item_id,)); conn.commit(); conn.close()
            self.refresh_data_and_ui(); self.estimate_frame.update_dropdowns()

class EstimateManagerWindow(ctk.CTkToplevel):
    def __init__(self, master, estimate_frame):
        super().__init__(master); self.estimate_frame = estimate_frame; self.title("Estimate Manager"); self.geometry("700x500"); self.grab_set(); self.after(250, lambda: self.iconbitmap(''))
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(1, weight=1)
        self.search_entry = ctk.CTkEntry(self, placeholder_text="Search"); self.search_entry.grid(row=0, column=0, padx=20, pady=(20,10), sticky="ew"); self.search_entry.bind("<KeyRelease>", self.filter_list)
        self.scroll_frame = ctk.CTkScrollableFrame(self, label_text="Saved Estimates"); self.scroll_frame.grid(row=1, column=0, padx=20, pady=(10,20), sticky="nsew")
        self.all_estimates = []; self.refresh_estimates()
    def refresh_estimates(self):
        conn = db_connect(); cursor = conn.cursor()
        query = """SELECT j.job_id, c.name, j.estimate_date, j.total_amount, j.job_name FROM estimate_jobs j JOIN customers c ON j.customer_id = c.id ORDER BY j.estimate_date DESC"""
        cursor.execute(query); self.all_estimates = cursor.fetchall(); conn.close(); self.display_estimates(self.all_estimates)
    def filter_list(self, event=None):
        search_term = self.search_entry.get().lower()
        if not search_term: self.display_estimates(self.all_estimates); return
        filtered = [est for est in self.all_estimates if search_term in est[1].lower() or (est[4] and search_term in est[4].lower())]
        self.display_estimates(filtered)
    def display_estimates(self, estimate_list):
        for widget in self.scroll_frame.winfo_children(): widget.destroy()
        for job_id, cust_name, date, total, job_name in estimate_list:
            row_frame = ctk.CTkFrame(self.scroll_frame); row_frame.pack(fill="x", padx=5, pady=4)
            job_display_name = f"{job_name} - " if job_name else ""; label_text = f"{job_display_name}{cust_name} - {date.split(' ')[0]} - ${total:,.2f}"
            label = ctk.CTkLabel(row_frame, text=label_text, anchor="w"); label.pack(side="left", fill="x", expand=True, padx=10)
            delete_btn = ctk.CTkButton(row_frame, text="Delete", width=60, fg_color="#D32F2F", hover_color="#C62828", command=lambda j=job_id: self.delete_job(j)); delete_btn.pack(side="right", padx=5)
            duplicate_btn = ctk.CTkButton(row_frame, text="Duplicate", width=80, command=lambda j=job_id: self.duplicate_job(j)); duplicate_btn.pack(side="right", padx=5)
            CTkToolTip(duplicate_btn, message="Create a new, editable copy of this estimate.")
            load_btn = ctk.CTkButton(row_frame, text="Load", width=50, command=lambda j=job_id: self.load_job(j)); load_btn.pack(side="right", padx=5)

    def delete_job(self, job_id):
        confirm_delete = True
        if load_setting('show_confirmations', 'True') == 'True':
            dialog = CustomMessageBox(self, title="Confirm Delete", message=f"Are you sure you want to delete this estimate? This cannot be undone.", buttons=["Yes", "No"])
            confirm_delete = dialog.get_result()
        if confirm_delete:
            conn = db_connect()
            cursor = conn.cursor()
            # Also delete associated line items for data integrity
            cursor.execute("DELETE FROM estimate_line_items WHERE job_id = ?", (job_id,))
            cursor.execute("DELETE FROM estimate_jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            conn.close()
            
            # If the deleted job is the one loaded on the main screen, clear the screen
            if self.estimate_frame.current_job_id == job_id:
                self.estimate_frame.clear_estimate()
                
            self.refresh_estimates()
    
    def duplicate_job(self, job_id):
        self.estimate_frame.load_estimate(job_id, is_duplicate=True); self.destroy()
    def load_job(self, job_id): 
        self.estimate_frame.load_estimate(job_id); self.destroy()

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Settings"); self.geometry("500x650"); self.grab_set(); self.after(250, lambda: self.iconbitmap(''))
        self.grid_columnconfigure(0, weight=1)
        financial_frame = ctk.CTkFrame(self); financial_frame.pack(pady=(20, 10), padx=20, fill="x"); financial_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(financial_frame, text="Financial Defaults", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, pady=(10,15), padx=10, sticky="w")
        
        ctk.CTkLabel(financial_frame, text="Default Markup (%):").grid(row=1, column=0, pady=10, padx=10, sticky="w")
        self.markup_entry = ctk.CTkEntry(financial_frame, placeholder_text="e.g., 20"); self.markup_entry.grid(row=1, column=1, pady=10, padx=10, sticky="ew")

        ctk.CTkLabel(financial_frame, text="Default Install Price ($):").grid(row=2, column=0, pady=10, padx=10, sticky="w")
        self.install_price_entry = ctk.CTkEntry(financial_frame, placeholder_text="e.g., 500"); self.install_price_entry.grid(row=2, column=1, pady=10, padx=10, sticky="ew")

        behavior_frame = ctk.CTkFrame(self); behavior_frame.pack(pady=10, padx=20, fill="x"); behavior_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(behavior_frame, text="Application Behavior", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, pady=(10,15), padx=10, sticky="w")
        ctk.CTkLabel(behavior_frame, text="Theme:").grid(row=1, column=0, pady=10, padx=10, sticky="w")
        self.theme_switch = ctk.CTkSwitch(behavior_frame, text="Dark", onvalue="dark", offvalue="light", command=lambda: self.master.toggle_theme(self.theme_switch.get())); self.theme_switch.grid(row=1, column=1, pady=10, padx=10, sticky="w")
        ctk.CTkLabel(behavior_frame, text="Show Delete Confirmations:").grid(row=2, column=0, pady=10, padx=10, sticky="w")
        self.confirmations_switch = ctk.CTkSwitch(behavior_frame, text="", onvalue="True", offvalue="False"); self.confirmations_switch.grid(row=2, column=1, pady=10, padx=10, sticky="w")
        data_frame = ctk.CTkFrame(self); data_frame.pack(pady=10, padx=20, fill="x"); data_frame.grid_columnconfigure((0,1), weight=1)
        ctk.CTkLabel(data_frame, text="Data Management", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, pady=(10,15), padx=10, sticky="w")
        self.backup_button = ctk.CTkButton(data_frame, text="Backup Database", command=self.master.backup_database); self.backup_button.grid(row=1, column=0, columnspan=2, pady=5, padx=10, sticky="ew")
        self.restore_button = ctk.CTkButton(data_frame, text="Restore Database", command=self.master.restore_database, fg_color="#D32F2F", hover_color="#C62828"); self.restore_button.grid(row=2, column=0, columnspan=2, pady=5, padx=10, sticky="ew")
        self.export_button = ctk.CTkButton(data_frame, text="Export Price List (CSV)", command=self.master.export_pricelist_csv); self.export_button.grid(row=3, column=0, pady=(15, 5), padx=10, sticky="ew")
        self.import_button = ctk.CTkButton(data_frame, text="Import Price List (CSV)", command=self.master.import_pricelist_csv); self.import_button.grid(row=3, column=1, pady=(15, 5), padx=10, sticky="ew")
        self.save_button = ctk.CTkButton(self, text="Save Settings", command=self.save_and_close); self.save_button.pack(side="right", pady=20, padx=20)
        self.load_settings()

    def load_settings(self):
        self.markup_entry.insert(0, load_setting('default_markup', ''))
        self.install_price_entry.insert(0, load_setting('default_install_price', ''))
        theme = load_setting('theme', 'dark')
        if theme == 'dark': self.theme_switch.select()
        else: self.theme_switch.deselect()
        show_confirmations = load_setting('show_confirmations', 'True')
        if show_confirmations == 'True': self.confirmations_switch.select()
        else: self.confirmations_switch.deselect()

    def save_and_close(self):
        save_setting('default_markup', self.markup_entry.get())
        save_setting('default_install_price', self.install_price_entry.get())
        save_setting('theme', self.theme_switch.get()); save_setting('show_confirmations', self.confirmations_switch.get())
        
        self.master.refresh_defaults_on_screen()
        self.destroy()

class EstimateFrame(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self.current_job_id = None; self.line_items = []; self.customers = {}; self.prices = {}; self.items_by_category = {}
        self.selected_customer_id = None; self.editing_item_index = None
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(2, weight=1)

        self.title = ctk.CTkLabel(self, text="Estimate Generator", font=ctk.CTkFont(size=18, weight="bold"))
        self.title.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10))

        self.header_container = ctk.CTkFrame(self, fg_color="transparent")
        self.header_container.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.header_container.grid_columnconfigure(1, weight=1)

        self.estimate_display_frame = ctk.CTkScrollableFrame(self, label_text="Line Items")
        self.estimate_display_frame.grid(row=2, column=0, columnspan=2, padx=20, pady=10, sticky="nsew")
        
        add_item_frame = ctk.CTkFrame(self, fg_color="transparent"); add_item_frame.grid(row=3, column=0, columnspan=2, padx=20, pady=0, sticky="ew"); add_item_frame.grid_columnconfigure((0,1), weight=1)
        ctk.CTkLabel(add_item_frame, text="Add from Price List:").grid(row=0, column=0, columnspan=4, sticky="w")
        self.category_est_menu = ctk.CTkOptionMenu(add_item_frame, values=["-"], command=self.update_item_menu); self.category_est_menu.grid(row=1, column=0, padx=(0,10), pady=5, sticky="ew")
        self.item_menu = ctk.CTkOptionMenu(add_item_frame, values=["-"]); self.item_menu.grid(row=1, column=1, padx=(0,10), pady=5, sticky="ew")
        self.quantity_entry = ctk.CTkEntry(add_item_frame, placeholder_text="Qty", width=80); self.quantity_entry.grid(row=1, column=2, padx=0, pady=5)
        self.add_item_button = ctk.CTkButton(add_item_frame, text="Add Item", command=self.add_or_update_item_in_estimate); self.add_item_button.grid(row=1, column=3, padx=10, pady=5)
        
        write_in_frame = ctk.CTkFrame(self, fg_color="transparent"); write_in_frame.grid(row=4, column=0, columnspan=2, padx=20, pady=(10,0), sticky="ew"); write_in_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(write_in_frame, text="Add Write-in Item/Service:").grid(row=0, column=0, columnspan=4, sticky="w")
        self.write_in_desc_entry = ctk.CTkEntry(write_in_frame, placeholder_text="Description"); self.write_in_desc_entry.grid(row=1, column=0, padx=(0,10), pady=5, sticky="ew")
        self.write_in_qty_entry = ctk.CTkEntry(write_in_frame, placeholder_text="Qty", width=80); self.write_in_qty_entry.grid(row=1, column=1, padx=0, pady=5)
        self.write_in_price_entry = ctk.CTkEntry(write_in_frame, placeholder_text="Unit Price ($)", width=120); self.write_in_price_entry.grid(row=1, column=2, padx=10, pady=5)
        self.add_write_in_button = ctk.CTkButton(write_in_frame, text="Add", command=self.add_write_in_item, width=60); self.add_write_in_button.grid(row=1, column=3, padx=0, pady=5)

        self.action_panel = ctk.CTkFrame(self, fg_color="transparent"); self.action_panel.grid(row=6, column=0, columnspan=2, sticky="se", padx=20, pady=(10, 20))
        self.new_button = ctk.CTkButton(self.action_panel, text="New Estimate", command=self.clear_estimate); self.new_button.pack(side="left", padx=(0, 10))
        self.save_button = ctk.CTkButton(self.action_panel, text="Save Estimate", command=self.save_estimate, fg_color="#1F8B4C", hover_color="#1A733F"); self.save_button.pack(side="left", padx=(0, 10))
        self.print_button = ctk.CTkButton(self.action_panel, text="Print Estimate", command=master.generate_and_print_estimate, fg_color="#555555", hover_color="#444444"); self.print_button.pack(side="left")
        
        self.delete_button = ctk.CTkButton(self.action_panel, text="Delete Estimate", command=self.delete_current_estimate, fg_color="#D32F2F", hover_color="#C62828")
        # The button is created but not packed here. It will be packed by other methods.
        
        CTkToolTip(self.delete_button, message="Delete the currently loaded estimate from the database.")
        
        self.clear_estimate()

    def _build_header_fields(self):
        for widget in self.header_container.winfo_children(): widget.destroy()
        ctk.CTkLabel(self.header_container, text="Customer:").grid(row=0, column=0, padx=(20,10), pady=(10, 5), sticky="w")
        self.customer_menu = ctk.CTkOptionMenu(self.header_container, values=["-"], command=self.set_customer)
        self.customer_menu.grid(row=0, column=1, padx=(0,20), pady=(10,5), sticky="ew")
        ctk.CTkLabel(self.header_container, text="Job Name:").grid(row=1, column=0, padx=(20,10), pady=5, sticky="w")
        self.job_name_entry = ctk.CTkEntry(self.header_container, placeholder_text="e.g., Kitchen Remodel")
        self.job_name_entry.grid(row=1, column=1, padx=(0,20), pady=5, sticky="ew")

    def _build_totals_frame(self):
        if hasattr(self, 'totals_frame') and self.totals_frame.winfo_exists():
            self.totals_frame.destroy()
        self.totals_frame = ctk.CTkFrame(self)
        self.totals_frame.grid(row=5, column=0, columnspan=2, padx=20, pady=10, sticky="e")
        self.totals_frame.grid_columnconfigure(1, weight=1)
        self.subtotal_label_text = ctk.CTkLabel(self.totals_frame, text="Subtotal:")
        self.subtotal_label_text.grid(row=0, column=0, columnspan=2, sticky="e", padx=10, pady=2)
        self.subtotal_label_value = ctk.CTkLabel(self.totals_frame, text="$0.00", font=ctk.CTkFont(weight="bold"))
        self.subtotal_label_value.grid(row=0, column=2, sticky="e", padx=10, pady=2)
        ctk.CTkLabel(self.totals_frame, text="Markup (%):").grid(row=1, column=0, sticky="w", padx=10, pady=2)
        self.markup_entry = ctk.CTkEntry(self.totals_frame, placeholder_text="%", width=120)
        self.markup_entry.grid(row=1, column=1, sticky="w", pady=2, padx=5)
        self.markup_label_value = ctk.CTkLabel(self.totals_frame, text="$0.00")
        self.markup_label_value.grid(row=1, column=2, sticky="e", padx=10, pady=2)
        ctk.CTkLabel(self.totals_frame, text="Installation Cost:").grid(row=2, column=0, sticky="w", padx=10, pady=2)
        install_entry_frame = ctk.CTkFrame(self.totals_frame, fg_color="transparent")
        install_entry_frame.grid(row=2, column=1, sticky="w", pady=2, padx=0)
        self.install_qty_entry = ctk.CTkEntry(install_entry_frame, placeholder_text="Qty", width=55)
        self.install_qty_entry.pack(side="left", padx=(5, 5))
        self.install_cost_entry = ctk.CTkEntry(install_entry_frame, placeholder_text="$", width=60)
        self.install_cost_entry.pack(side="left")
        self.install_label_value = ctk.CTkLabel(self.totals_frame, text="$0.00")
        self.install_label_value.grid(row=2, column=2, sticky="e", padx=10, pady=2)
        ctk.CTkLabel(self.totals_frame, text="Misc. Charge:").grid(row=3, column=0, sticky="w", padx=10, pady=2)
        self.misc_entry = ctk.CTkEntry(self.totals_frame, placeholder_text="$", width=120)
        self.misc_entry.grid(row=3, column=1, sticky="w", pady=2, padx=5)
        self.misc_label_value = ctk.CTkLabel(self.totals_frame, text="$0.00")
        self.misc_label_value.grid(row=3, column=2, sticky="e", padx=10, pady=2)
        self.grand_total_label_text = ctk.CTkLabel(self.totals_frame, text="Grand Total:", font=ctk.CTkFont(size=16, weight="bold"))
        self.grand_total_label_text.grid(row=4, column=0, columnspan=2, sticky="e", padx=10, pady=5)
        self.grand_total_label_value = ctk.CTkLabel(self.totals_frame, text="$0.00", font=ctk.CTkFont(size=16, weight="bold"))
        self.grand_total_label_value.grid(row=4, column=2, sticky="e", padx=10, pady=5)
        for entry in [self.markup_entry, self.install_qty_entry, self.misc_entry]:
            entry.bind("<KeyRelease>", self.recalculate_totals_event)
        self.install_cost_entry.bind("<KeyRelease>", self._handle_install_cost_entry)

    def _handle_install_cost_entry(self, event=None):
        if self.install_cost_entry.get() and not self.install_qty_entry.get():
            self.install_qty_entry.insert(0, "1")
        self.recalculate_totals()

    def clear_estimate(self):
        self.current_job_id = None; self.line_items = []; self.selected_customer_id = None
        self._build_header_fields()
        self._build_totals_frame()
        self.update_dropdowns()
        default_markup = load_setting('default_markup', '')
        if default_markup: self.markup_entry.insert(0, default_markup)
        default_install = load_setting('default_install_price', '')
        if default_install: self.install_cost_entry.insert(0, default_install)
        self.refresh_estimate_display()
        self.recalculate_totals()
        # Hide the delete button for a new estimate
        self.delete_button.pack_forget()
    
    def delete_current_estimate(self):
        if not self.current_job_id:
            CustomMessageBox(self, title="Error", message="This is a new estimate and has not been saved yet.").get_result()
            return
        
        customer_name = self.customer_menu.get()
        job_name = self.job_name_entry.get().strip()
        display_text = f"the estimate '{job_name}' for {customer_name}" if job_name else f"the estimate for {customer_name}"
        
        confirm_delete = True
        if load_setting('show_confirmations', 'True') == 'True':
            dialog = CustomMessageBox(self, title="Confirm Delete", 
                                      message=f"Are you sure you want to permanently delete {display_text}? This action cannot be undone.", 
                                      buttons=["Yes", "No"])
            confirm_delete = dialog.get_result()
            
        if confirm_delete:
            try:
                conn = db_connect()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM estimate_jobs WHERE job_id = ?", (self.current_job_id,))
                cursor.execute("DELETE FROM estimate_line_items WHERE job_id = ?", (self.current_job_id,))
                conn.commit()
                conn.close()
                self.clear_estimate()
            except Exception as e:
                CustomMessageBox(self, title="Database Error", message=f"Could not delete estimate: {e}").get_result()

    def load_estimate(self, job_id, is_duplicate=False):
        self.clear_estimate() # Start with a clean slate
        
        conn = db_connect(); cursor = conn.cursor()
        cursor.execute("SELECT customer_id, job_name, install_total, markup_percent, misc_charge, install_qty, install_unit_price FROM estimate_jobs WHERE job_id = ?", (job_id,));
        job_info = cursor.fetchone()
        if not job_info: conn.close(); return

        if not is_duplicate:
            self.current_job_id = job_id
            # Show the delete button because a saved estimate is loaded
            self.delete_button.pack(side="left", padx=(10, 0))

        cust_id, job_name, install_total, markup_percent, misc_charge, install_qty, install_unit_price = job_info
        cust_name = self.customer_names_by_id.get(cust_id, "-"); self.customer_menu.set(cust_name); self.selected_customer_id = cust_id
        self.job_name_entry.insert(0, job_name or "")
        cursor.execute("SELECT item_name, category_name, quantity, unit_price, line_total FROM estimate_line_items WHERE job_id = ?", (job_id,)); items = cursor.fetchall()
        for name, cat_name, qty, unit_p, total_p in items:
            self.line_items.append({"name": name, "category": cat_name or "Write-in", "qty": qty, "unit_price": unit_p, "total": total_p})

        # Clear fields before inserting loaded values to prevent doubling
        markup_val = markup_percent or 0.0
        self.markup_entry.delete(0, 'end')
        self.markup_entry.insert(0, str(int(markup_val)) if markup_val == int(markup_val) else str(markup_val))
        
        # Clear installation fields before inserting
        self.install_qty_entry.delete(0, 'end')
        self.install_cost_entry.delete(0, 'end')
        
        if install_qty is not None and install_unit_price is not None and install_qty > 0:
            self.install_qty_entry.insert(0, str(int(install_qty)) if install_qty == int(install_qty) else str(install_qty))
            self.install_cost_entry.insert(0, str(int(install_unit_price)) if install_unit_price == int(install_unit_price) else f"{install_unit_price:.2f}")
        elif install_total > 0:
            # Fallback for older data that only saved total install cost
            self.install_qty_entry.insert(0, "1")
            self.install_cost_entry.insert(0, str(int(install_total)) if install_total == int(install_total) else f"{install_total:.2f}")
        
        misc_val = misc_charge or 0.0
        self.misc_entry.delete(0, 'end')
        self.misc_entry.insert(0, str(int(misc_val)) if misc_val == int(misc_val) else str(misc_val))
        
        conn.close(); self.refresh_estimate_display()
        if is_duplicate:
            self.current_job_id = None
            original_job_name = self.job_name_entry.get()
            self.job_name_entry.delete(0, 'end')
            self.job_name_entry.insert(0, f"{original_job_name} (Copy)")
            # Hide delete button on a duplicated (unsaved) copy
            self.delete_button.pack_forget()

    def recalculate_totals_event(self, event=None): self.recalculate_totals()
    def recalculate_totals(self):
        subtotal = sum(item['total'] for item in self.line_items)
        try: markup_percent = float(self.markup_entry.get() or 0)
        except ValueError: markup_percent = 0
        markup_amount = subtotal * (markup_percent / 100); total_after_markup = subtotal + markup_amount
        try: install_qty = float(self.install_qty_entry.get() or 0)
        except ValueError: install_qty = 0
        try: install_unit_cost = float(self.install_cost_entry.get() or 0)
        except ValueError: install_unit_cost = 0
        install_total = install_qty * install_unit_cost
        try: misc_charge = float(self.misc_entry.get() or 0)
        except ValueError: misc_charge = 0
        grand_total = total_after_markup + install_total + misc_charge
        self.subtotal_label_value.configure(text=f"${subtotal:,.2f}"); self.markup_label_value.configure(text=f"${markup_amount:,.2f}"); self.install_label_value.configure(text=f"${install_total:,.2f}"); self.misc_label_value.configure(text=f"${misc_charge:,.2f}"); self.grand_total_label_value.configure(text=f"${grand_total:,.2f}")
    def add_write_in_item(self):
        desc = self.write_in_desc_entry.get(); qty_str = self.write_in_qty_entry.get(); price_str = self.write_in_price_entry.get()
        if not desc or not qty_str or not price_str: return
        try: qty = int(qty_str); price = float(price_str)
        except ValueError: CustomMessageBox(self, title="Input Error", message="Quantity and Price must be valid numbers.").get_result(); return
        new_item_data = {"category": "Write-in", "name": desc, "qty": qty, "unit_price": price, "total": qty * price}
        self.line_items.append(new_item_data); self.write_in_desc_entry.delete(0, 'end'); self.write_in_qty_entry.delete(0, 'end'); self.write_in_price_entry.delete(0, 'end'); self.refresh_estimate_display()
    def delete_item_from_estimate(self, index):
        confirm_delete = True
        if load_setting('show_confirmations', 'True') == 'True':
            dialog = CustomMessageBox(self, title="Confirm Delete", message=f"Are you sure you want to delete this item?", buttons=["Yes", "No"])
            confirm_delete = dialog.get_result()
        if confirm_delete:
            self.line_items.pop(index); self.refresh_estimate_display()
    def populate_edit_form(self, index):
        self.editing_item_index = index; item_data = self.line_items[index]; self.quantity_entry.delete(0, 'end')
        self.category_est_menu.set(item_data['category']); self.update_item_menu(item_data['category']); self.item_menu.set(item_data['name'])
        self.quantity_entry.insert(0, str(item_data['qty'])); self.add_item_button.configure(text="Update Item")
    def add_or_update_item_in_estimate(self):
        category_name = self.category_est_menu.get(); item_name = self.item_menu.get(); quantity_str = self.quantity_entry.get()
        if item_name == "-" or not quantity_str or self.selected_customer_id is None: return
        try:
            quantity = int(quantity_str); unit_price = self.prices[item_name]; line_total = quantity * unit_price
            new_item_data = {"category": category_name, "name": item_name, "qty": quantity, "unit_price": unit_price, "total": line_total}
            if self.editing_item_index is not None:
                self.line_items.pop(self.editing_item_index); self.line_items.insert(self.editing_item_index, new_item_data)
            else: self.line_items.append(new_item_data)
            self.quantity_entry.delete(0, 'end'); self.editing_item_index = None; self.add_item_button.configure(text="Add Item"); self.refresh_estimate_display()
        except (ValueError, KeyError): pass
    def move_item_in_estimate(self, index, direction):
        if direction == 'up' and index > 0: self.line_items[index], self.line_items[index - 1] = self.line_items[index - 1], self.line_items[index]
        elif direction == 'down' and index < len(self.line_items) - 1: self.line_items[index], self.line_items[index + 1] = self.line_items[index + 1], self.line_items[index]
        self.refresh_estimate_display()
    def refresh_estimate_display(self):
        for widget in self.estimate_display_frame.winfo_children(): widget.destroy()
        for index, item in enumerate(self.line_items):
            row_frame = ctk.CTkFrame(self.estimate_display_frame, fg_color="transparent"); row_frame.pack(fill="x")
            text = f"{item['qty']} x {item['name']} @ ${item['unit_price']:.2f} = ${item['total']:.2f}"
            label = ctk.CTkLabel(row_frame, text=text, anchor="w"); label.pack(side="left", padx=10, pady=2, fill="x", expand=True)
            down_button = ctk.CTkButton(row_frame, text="▼", width=30, command=lambda i=index: self.move_item_in_estimate(i, 'down')); down_button.pack(side="right", padx=(5,10), pady=2)
            if index == len(self.line_items) - 1: down_button.configure(state="disabled")
            up_button = ctk.CTkButton(row_frame, text="▲", width=30, command=lambda i=index: self.move_item_in_estimate(i, 'up')); up_button.pack(side="right", padx=5, pady=2)
            if index == 0: up_button.configure(state="disabled")
            delete_btn = ctk.CTkButton(row_frame, text="Delete", width=60, fg_color="#D32F2F", hover_color="#C62828", command=lambda i=index: self.delete_item_from_estimate(i)); delete_btn.pack(side="right", padx=5, pady=2)
            edit_btn = ctk.CTkButton(row_frame, text="Edit", width=50, command=lambda i=index: self.populate_edit_form(i)); edit_btn.pack(side="right", padx=5, pady=2)
        self.recalculate_totals()
    def update_dropdowns(self):
        conn = db_connect(); cursor = conn.cursor(); cursor.execute("SELECT id, name FROM customers ORDER BY name"); customers = cursor.fetchall(); customer_names = [name for id, name in customers]
        self.customers = {name: id for id, name in customers}; self.customer_names_by_id = {id: name for id, name in customers}; self.customer_menu.configure(values=customer_names if customer_names else ["-"])
        if not customer_names: self.customer_menu.set("-")
        cursor.execute("SELECT name FROM categories ORDER BY sort_order ASC"); categories = [row[0] for row in cursor.fetchall()]
        self.category_est_menu.configure(values=categories if categories else ["-"])
        if not categories: self.category_est_menu.set("-")
        cursor.execute("""SELECT c.name, p.item_name, p.unit_price FROM pricelist p JOIN categories c ON p.category_id = c.id ORDER BY c.name, p.sort_order""")
        self.items_by_category.clear(); self.prices.clear()
        for cat_name, item_name, price in cursor.fetchall():
            if cat_name not in self.items_by_category: self.items_by_category[cat_name] = []
            self.items_by_category[cat_name].append(item_name); self.prices[item_name] = price
        conn.close(); self.update_item_menu(self.category_est_menu.get())
    def update_item_menu(self, category):
        items = self.items_by_category.get(category, []); self.item_menu.configure(values=items if items else ["-"]); self.item_menu.set(items[0] if items else "-")
    def set_customer(self, selected_name): self.selected_customer_id = self.customers.get(selected_name)
    def save_estimate(self):
        if not self.selected_customer_id: CustomMessageBox(self, title="Save Error", message="Please select a customer before saving.").get_result(); return
        job_name = self.job_name_entry.get().strip()
        try: markup_percent = float(self.markup_entry.get() or 0)
        except ValueError: markup_percent = 0
        try: install_qty = float(self.install_qty_entry.get() or 0)
        except ValueError: install_qty = 0
        try: install_unit_cost = float(self.install_cost_entry.get() or 0)
        except ValueError: install_unit_cost = 0
        install_total = install_qty * install_unit_cost
        try: misc_charge = float(self.misc_entry.get() or 0)
        except ValueError: misc_charge = 0
        conn = db_connect(); cursor = conn.cursor(); date_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        subtotal = sum(item['total'] for item in self.line_items); markup_amount = subtotal * (markup_percent / 100)
        grand_total = subtotal + markup_amount + install_total + misc_charge
        
        if self.current_job_id is None:
            cursor.execute("""INSERT INTO estimate_jobs (customer_id, job_name, estimate_date, total_amount, install_total, markup_percent, misc_charge, install_qty, install_unit_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                           (self.selected_customer_id, job_name, date_str, grand_total, install_total, markup_percent, misc_charge, install_qty, install_unit_cost)); self.current_job_id = cursor.lastrowid
        else:
            cursor.execute("""UPDATE estimate_jobs SET job_name=?, estimate_date=?, total_amount=?, install_total=?, markup_percent=?, misc_charge=?, install_qty=?, install_unit_price=? WHERE job_id=?""",
                           (job_name, date_str, grand_total, install_total, markup_percent, misc_charge, install_qty, install_unit_cost, self.current_job_id))
            cursor.execute("DELETE FROM estimate_line_items WHERE job_id = ?", (self.current_job_id,))
            
        for item in self.line_items: cursor.execute("INSERT INTO estimate_line_items (job_id, item_name, category_name, quantity, unit_price, line_total) VALUES (?, ?, ?, ?, ?, ?)",
                           (self.current_job_id, item['name'], item['category'], item['qty'], item['unit_price'], item['total']))
        conn.commit(); conn.close()
        
        self.delete_button.pack(side="left", padx=(10, 0))
        
        customer_name = self.customer_menu.get()
        display_text = f"'{job_name}' for {customer_name}" if job_name else f"Estimate for {customer_name}"
        CustomMessageBox(self, title="Success", message=f"{display_text} has been saved successfully.").get_result()

class CabinetEstimatorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        setup_database()
        
        self.iconbitmap(resource_path("door_icon.ico"))
        self.title("Custom Cabinet Estimator"); self.geometry("950x800")
        
        initial_theme = load_setting('theme', 'dark')
        ctk.set_appearance_mode(initial_theme)

        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
        self.pricelist_window = None; self.estimate_manager_window = None; self.customer_manager_window = None; self.settings_window = None
        
        self.left_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)

        ctk.CTkLabel(self.left_panel, text="Management", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(10,20))
        self.manage_customers_button = ctk.CTkButton(self.left_panel, text="Manage Customers", command=self.open_customer_manager)
        self.manage_customers_button.pack(fill="x", padx=20, pady=5)
        
        self.manage_pricelist_button = ctk.CTkButton(self.left_panel, text="Manage Price List", command=self.open_pricelist_manager)
        self.manage_pricelist_button.pack(fill="x", padx=20, pady=5)
        
        self.manage_estimates_button = ctk.CTkButton(self.left_panel, text="Manage Estimates", command=self.open_estimate_manager)
        self.manage_estimates_button.pack(fill="x", padx=20, pady=5)
        
        self.bind("<Control-s>", lambda event: self.estimate_frame.save_estimate())
        self.bind("<Control-n>", lambda event: self.estimate_frame.clear_estimate())
        self.bind("<Control-p>", lambda event: self.generate_and_print_estimate())
        
        self.bottom_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.bottom_frame.pack(side="bottom", fill="x", padx=10)
        
        self.settings_button = ctk.CTkButton(self.bottom_frame, text="Settings", command=self.open_settings_window)
        self.settings_button.pack(side="left", padx=10, pady=10)
        
        self.estimate_frame = EstimateFrame(self)
        self.estimate_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)

    def toggle_theme(self, new_mode):
        """Sets the application theme based on the provided mode."""
        ctk.set_appearance_mode(new_mode)
        
    def refresh_defaults_on_screen(self):
        """Called from settings to update the main estimate screen with new defaults."""
        if self.estimate_frame:
            self.estimate_frame.clear_estimate()

    def open_customer_manager(self):
        if self.customer_manager_window is None or not self.customer_manager_window.winfo_exists(): self.customer_manager_window = CustomerManagerWindow(self, estimate_frame=self.estimate_frame)
        self.customer_manager_window.focus()
        
    def open_pricelist_manager(self):
        if self.pricelist_window is None or not self.pricelist_window.winfo_exists(): self.pricelist_window = PriceListWindow(self, estimate_frame=self.estimate_frame)
        self.pricelist_window.focus()
        
    def open_estimate_manager(self):
        if self.estimate_manager_window is None or not self.estimate_manager_window.winfo_exists(): self.estimate_manager_window = EstimateManagerWindow(self, estimate_frame=self.estimate_frame)
        else: self.estimate_manager_window.focus(); self.estimate_manager_window.refresh_estimates()
        
    def open_settings_window(self):
        if self.settings_window is None or not self.settings_window.winfo_exists():
            self.settings_window = SettingsWindow(self)
        self.settings_window.focus()
    
    # --- MODIFICATION START ---
    def backup_database(self):
        source_path = os.path.join(get_app_data_path(), 'database.db')
        if not os.path.exists(source_path):
            CustomMessageBox(self, title="Error", message="Database file not found.").get_result()
            return
        
        backup_path = tkinter.filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("Database Files", "*.db")],
            title="Save Database Backup As...",
            initialfile=f"backup_{datetime.now().strftime('%Y-%m-%d')}.db"
        )
        
        if backup_path:
            try:
                shutil.copy(source_path, backup_path)
                CustomMessageBox(self, title="Success", message=f"Database backed up successfully to:\n{backup_path}").get_result()
            except Exception as e:
                CustomMessageBox(self, title="Error", message=f"Could not save backup: {e}").get_result()

    def restore_database(self):
        confirm = CustomMessageBox(self, title="Confirm Restore", 
                                   message="WARNING: This will overwrite the current database with the selected backup file. This action cannot be undone. Are you sure you want to continue?",
                                   buttons=["Yes", "No"]).get_result()
        if not confirm:
            return

        backup_path = tkinter.filedialog.askopenfilename(
            filetypes=[("Database Files", "*.db"), ("All files", "*.*")],
            title="Select Database Backup to Restore"
        )
        if backup_path:
            try:
                if self.pricelist_window and self.pricelist_window.winfo_exists(): self.pricelist_window.destroy()
                if self.estimate_manager_window and self.estimate_manager_window.winfo_exists(): self.estimate_manager_window.destroy()
                if self.customer_manager_window and self.customer_manager_window.winfo_exists(): self.customer_manager_window.destroy()
                if self.settings_window and self.settings_window.winfo_exists(): self.settings_window.destroy()
                
                shutil.copy(backup_path, os.path.join(get_app_data_path(), 'database.db'))
                
                self.estimate_frame.update_dropdowns()
                
                CustomMessageBox(self, title="Success", message="Database restored successfully. It's recommended to restart the application.").get_result()
            except Exception as e:
                CustomMessageBox(self, title="Error", message=f"Could not restore database: {e}").get_result()
    # --- MODIFICATION END ---
    
    def export_pricelist_csv(self):
        file_path = tkinter.filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            title="Export Price List As...",
            initialfile=f"pricelist_export_{datetime.now().strftime('%Y-%m-%d')}.csv"
        )
        if file_path:
            try:
                conn = db_connect()
                cursor = conn.cursor()
                query = """SELECT c.name, p.item_name, p.unit_price FROM pricelist p JOIN categories c ON p.category_id = c.id ORDER BY c.sort_order, p.sort_order"""
                cursor.execute(query)
                items = cursor.fetchall()
                conn.close()
                
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Category', 'ItemName', 'UnitPrice'])
                    writer.writerows(items)
                
                CustomMessageBox(self, title="Success", message=f"Price list exported to:\n{file_path}").get_result()
            except Exception as e:
                CustomMessageBox(self, title="Error", message=f"Failed to export price list: {e}").get_result()

    def import_pricelist_csv(self):
        confirm = CustomMessageBox(self, title="Confirm Import", 
                                   message="WARNING: This will delete your entire current price list and replace it with data from the CSV file. This cannot be undone. Are you sure you want to continue?",
                                   buttons=["Yes", "No"]).get_result()
        if not confirm:
            return
            
        file_path = tkinter.filedialog.askopenfilename(
            filetypes=[("CSV Files", "*.csv")],
            title="Select CSV File to Import"
        )
        if file_path:
            conn = db_connect()
            cursor = conn.cursor()
            try:
                with open(file_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    header = next(reader)
                    
                    cursor.execute("BEGIN TRANSACTION")
                    cursor.execute("DELETE FROM pricelist")
                    
                    categories_cache = {name: cat_id for cat_id, name in cursor.execute("SELECT id, name FROM categories").fetchall()}
                    
                    for row in reader:
                        cat_name, item_name, unit_price = row
                        
                        if cat_name not in categories_cache:
                            cursor.execute("INSERT INTO categories (name, sort_order) VALUES (?, (SELECT IFNULL(MAX(sort_order), 0) + 1 FROM categories))", (cat_name,))
                            categories_cache[cat_name] = cursor.lastrowid
                        
                        cat_id = categories_cache[cat_name]
                        cursor.execute("INSERT INTO pricelist (category_id, item_name, unit_price, sort_order) VALUES (?, ?, ?, (SELECT IFNULL(MAX(sort_order), 0) + 1 FROM pricelist WHERE category_id = ?))",
                                       (cat_id, item_name, float(unit_price), cat_id))
                
                conn.commit()
                CustomMessageBox(self, title="Success", message="Price list imported successfully.").get_result()
            except Exception as e:
                conn.rollback()
                CustomMessageBox(self, title="Error", message=f"Failed to import price list: {e}").get_result()
            finally:
                conn.close()
                self.estimate_frame.update_dropdowns()
                
    def show_about_dialog(self):
        CustomMessageBox(self, title="About", 
                         message="Custom Cabinet Estimator\n\nVersion: 1.0\nCreated with CustomTkinter.")

    def generate_and_print_estimate(self):
        estimate_frame = self.estimate_frame
        cust_id = estimate_frame.selected_customer_id
        if not cust_id:
            CustomMessageBox(self, title="Error", message="Please select a customer.").get_result()
            return

        line_items = estimate_frame.line_items
        subtotal = sum(item['total'] for item in line_items)
        
        try:
            install_qty = float(estimate_frame.install_qty_entry.get() or 0)
        except ValueError:
            install_qty = 0
        try:
            install_unit_cost = float(estimate_frame.install_cost_entry.get() or 0)
        except ValueError:
            install_unit_cost = 0
        install_total = install_qty * install_unit_cost
            
        try:
            markup_percent = float(estimate_frame.markup_entry.get() or 0)
        except ValueError:
            markup_percent = 0
            
        markup_amount = subtotal * (markup_percent / 100)
        
        try:
            misc_charge = float(estimate_frame.misc_entry.get() or 0)
        except ValueError:
            misc_charge = 0
            
        grand_total = subtotal + markup_amount + install_total + misc_charge

        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute("SELECT name, address, phone, email FROM customers WHERE id = ?", (cust_id,))
        customer_info = cursor.fetchone()
        conn.close()
        
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
                pdf_filename = tmp_pdf.name
            
            pdf = FPDF()
            pdf.add_page()
            
            pdf.set_font("Helvetica", 'B', 18)
            pdf.cell(0, 10, 'Custom Cabinet Estimate', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
            pdf.ln(5)
            
            pdf.set_font("Helvetica", 'B', 12)
            pdf.cell(0, 6, f"{customer_info[0]}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("Helvetica", '', 12)
            
            if customer_info[1]: 
                pdf.cell(0, 6, f"{customer_info[1]}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            
            if customer_info[2]:
                pdf.cell(0, 6, f"{customer_info[2]}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            
            pdf.cell(0, 6, f"{datetime.now().strftime('%m-%d-%Y')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(10)
            
            pdf.set_font('Helvetica', 'B', 12)
            pdf.cell(95, 8, 'Item Description', border='B', align='L')
            pdf.cell(25, 8, 'Quantity', border='B', align='C')
            pdf.cell(35, 8, 'Unit Price', border='B', align='R')
            pdf.cell(35, 8, 'Total Price', border='B', align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)
            
            pdf.set_font('Helvetica', '', 12)
            if line_items:
                for item in line_items:
                    pdf.cell(95, 8, item['name'], border=0, align='L')
                    pdf.cell(25, 8, str(item['qty']), border=0, align='C')
                    pdf.cell(35, 8, f"${item['unit_price']:.2f}", border=0, align='R')
                    pdf.cell(35, 8, f"${item['total']:.2f}", border=0, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)
            
            pdf.set_font('Helvetica', 'B', 12)
            pdf.cell(155, 8, 'Subtotal:', align='R')
            pdf.cell(35, 8, f"${subtotal:,.2f}", align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            
            pdf.set_font('Helvetica', '', 12)
            if markup_amount > 0:
                pdf.cell(155, 8, f'Markup ({markup_percent}%):', align='R')
                pdf.cell(35, 8, f"${markup_amount:,.2f}", align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if install_total > 0:
                pdf.cell(155, 8, 'Installation:', align='R')
                pdf.cell(35, 8, f"${install_total:,.2f}", align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if misc_charge != 0:
                pdf.cell(155, 8, 'Misc:', align='R')
                pdf.cell(35, 8, f"${misc_charge:,.2f}", align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            pdf.set_font('Helvetica', 'B', 14)
            pdf.cell(155, 10, 'Grand Total:', border='T', align='R')
            pdf.cell(35, 10, f"${grand_total:,.2f}", border='T', align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            pdf.output(pdf_filename)
            
            PDFViewerWindow(self, pdf_path=pdf_filename)
            
        except Exception as e:
            CustomMessageBox(self, title="Error", message=f"Failed to generate PDF for preview:\n{e}").get_result()

if __name__ == "__main__":
    app = CabinetEstimatorApp()
    app.mainloop()
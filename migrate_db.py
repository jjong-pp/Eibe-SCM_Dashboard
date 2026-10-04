import sqlite3

conn = sqlite3.connect('data/local_erp.db')
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE MONTHLY_ORDER_PLAN ADD COLUMN arrival_month TEXT")
    print("Column added successfully.")
except sqlite3.OperationalError as e:
    print("Error:", e)

conn.commit()
conn.close()

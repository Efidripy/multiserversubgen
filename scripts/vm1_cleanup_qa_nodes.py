import sqlite3

conn = sqlite3.connect('/opt/sub-manager/admin.db')
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM nodes WHERE name LIKE 'qa-%'")
before = cur.fetchone()[0]
cur.execute("DELETE FROM nodes WHERE name LIKE 'qa-%'")
conn.commit()
cur.execute("SELECT COUNT(*) FROM nodes WHERE name LIKE 'qa-%'")
after = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM nodes")
total = cur.fetchone()[0]
conn.close()

print(f"qa_before={before}")
print(f"qa_after={after}")
print(f"total_nodes={total}")

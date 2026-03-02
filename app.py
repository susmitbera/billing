from flask import Flask, render_template, request, redirect, url_for, send_file, flash
import sqlite3, os, json
from fpdf import FPDF
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.secret_key = "saree_shop_secret"

# Load config
if os.path.exists("config.json"):
    with open("config.json") as f:
        config = json.load(f)
else:
    config = {"invoice_folder": "invoices"}
os.makedirs(config["invoice_folder"], exist_ok=True)

# Database
conn = sqlite3.connect("saree_shop_web.db", check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS inventory(
    id INTEGER PRIMARY KEY,
    name TEXT,
    code TEXT UNIQUE,
    price REAL,
    quantity INTEGER
)''')
c.execute('''CREATE TABLE IF NOT EXISTS sales(
    id INTEGER PRIMARY KEY,
    invoice_name TEXT,
    date TEXT
)''')
conn.commit()

# Cleanup old invoices
def cleanup_invoices():
    folder = config["invoice_folder"]
    now = datetime.now()
    six_months_ago = now - timedelta(days=180)
    for f in os.listdir(folder):
        path = os.path.join(folder, f)
        if os.path.isfile(path):
            created = datetime.fromtimestamp(os.path.getctime(path))
            if created < six_months_ago:
                os.remove(path)

scheduler = BackgroundScheduler()
scheduler.add_job(func=cleanup_invoices, trigger="interval", days=1)
scheduler.start()

# Inventory page
@app.route("/inventory", methods=["GET", "POST"])
def inventory():
    if request.method == "POST":
        name = request.form["name"]
        code = request.form["code"]
        price = float(request.form["price"])
        qty = int(request.form["quantity"])
        try:
            c.execute("INSERT INTO inventory(name, code, price, quantity) VALUES (?,?,?,?)", 
                      (name, code, price, qty))
            conn.commit()
            flash(f"'{name}' added to inventory!", "success")
        except sqlite3.IntegrityError:
            flash("Code already exists!", "danger")
        return redirect(url_for("inventory"))
    c.execute("SELECT * FROM inventory")
    items = c.fetchall()
    return render_template("inventory.html", items=items)

# Billing page
@app.route("/", methods=["GET", "POST"])
def index():
    c.execute("SELECT * FROM inventory")
    items = c.fetchall()
    if request.method == "POST":
        bill_items = request.form.getlist("bill_items")  # format: code,qty
        bill_data = []
        total_amount = 0
        for b in bill_items:
            if not b.strip(): 
                continue
            code, qty = b.split(",")
            qty = int(qty)
            c.execute("SELECT name, price, quantity FROM inventory WHERE code=?", (code,))
            result = c.fetchone()
            if not result:
                continue
            name, price, stock_qty = result
            if qty > stock_qty:
                flash(f"Only {stock_qty} in stock for {name}", "danger")
                continue
            total = price * qty
            bill_data.append({"name": name, "code": code, "price": price, "quantity": qty, "total": total})
            total_amount += total
            c.execute("UPDATE inventory SET quantity = quantity - ? WHERE code=?", (qty, code))
        conn.commit()

        # Generate PDF invoice
        invoice_name = f"invoice_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(200, 10, "Saree Shop Invoice", ln=1, align="C")
        pdf.set_font("Arial", size=12)
        pdf.ln(10)
        pdf.cell(40,10,"Name",1)
        pdf.cell(30,10,"Code",1)
        pdf.cell(30,10,"Price",1)
        pdf.cell(20,10,"Qty",1)
        pdf.cell(30,10,"Total",1)
        pdf.ln()
        for item in bill_data:
            pdf.cell(40,10,item["name"],1)
            pdf.cell(30,10,item["code"],1)
            pdf.cell(30,10,str(item["price"]),1)
            pdf.cell(20,10,str(item["quantity"]),1)
            pdf.cell(30,10,str(item["total"]),1)
            pdf.ln()
        pdf.ln(5)
        pdf.cell(200,10,f"Total Amount: {total_amount}", ln=1)
        invoice_path = os.path.join(config["invoice_folder"], invoice_name)
        pdf.output(invoice_path)
        c.execute("INSERT INTO sales(invoice_name,date) VALUES (?,?)", (invoice_name, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
        flash(f"Invoice generated: {invoice_name}", "success")
        return send_file(invoice_path, as_attachment=True)
    return render_template("index.html", items=items)

# Change invoice folder
@app.route("/set_folder", methods=["POST"])
def set_folder():
    folder = request.form["folder"]
    os.makedirs(folder, exist_ok=True)
    config["invoice_folder"] = folder
    with open("config.json", "w") as f:
        json.dump(config, f)
    flash(f"Invoice folder set to: {folder}", "success")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
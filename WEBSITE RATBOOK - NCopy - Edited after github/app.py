from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
import os
import json

# --- KONFIGURASI APP ---
app = Flask(__name__, static_folder='static')
app.secret_key = 'rahasia_negara_ratbook_secure_key'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # Max upload 16MB

# Database & Upload Path
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'ratbook.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)

# --- MODEL DATABASE ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    # Kategori: ASET, KEWAJIBAN, MODAL, PENDAPATAN, HPP, BEBAN
    category = db.Column(db.String(50), nullable=False) 
    normal_balance = db.Column(db.String(10), nullable=False) # debit / credit
    
    def to_dict(self):
        return {
            'id': self.id, 'code': self.code, 'name': self.name,
            'category': self.category, 'normal_balance': self.normal_balance
        }

class Product(db.Model):
    # Untuk Inventory Moving Average
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    qty = db.Column(db.Integer, default=0)
    avg_cost = db.Column(db.Float, default=0) # Harga Rata-rata Bergerak
    
    def to_dict(self):
        return {
            'id': self.id, 'code': self.code, 'name': self.name,
            'qty': self.qty, 'avg_cost': self.avg_cost,
            'total_value': self.qty * self.avg_cost
        }

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    due_date = db.Column(db.Date, nullable=True)
    description = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50), default="Umum") # Umum, Penyesuaian, Penjualan, Pembelian
    proof_file = db.Column(db.String(200), nullable=True)
    
    entries = db.relationship('JournalEntry', backref='transaction', cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.strftime('%Y-%m-%d'),
            'due_date': self.due_date.strftime('%Y-%m-%d') if self.due_date else '-',
            'description': self.description,
            'type': self.type,
            'proof': self.proof_file,
            'entries': [e.to_dict() for e in self.entries]
        }

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    debit = db.Column(db.Float, default=0)
    credit = db.Column(db.Float, default=0)
    sub_ledger_name = db.Column(db.String(100), nullable=True) # Relasi (Utang/Piutang)
    
    account = db.relationship('Account')

    def to_dict(self):
        return {
            'account_id': self.account_id,
            'account_name': self.account.name,
            'account_code': self.account.code,
            'account_category': self.account.category,
            'debit': self.debit,
            'credit': self.credit,
            'sub_name': self.sub_ledger_name
        }

# --- SEEDING DATA ---
def seed_data():
    # 1. Seed User Admin
    if not User.query.filter_by(username='admin').first():
        u = User(username='admin', email='admin@ratbook.com')
        u.set_password('admin')
        db.session.add(u)
        db.session.commit()
        print("User Admin dibuat (admin/admin)")

    # 2. Seed Accounts
    if Account.query.first(): return

    initial_accounts = [
        Account(code='1-1000', name='Kas', category='ASET', normal_balance='debit'),
        Account(code='1-1100', name='Bank', category='ASET', normal_balance='debit'),
        Account(code='1-1200', name='Piutang Usaha', category='ASET', normal_balance='debit'),
        Account(code='1-1300', name='Persediaan Barang', category='ASET', normal_balance='debit'),
        Account(code='1-1400', name='Sewa Dibayar Dimuka', category='ASET', normal_balance='debit'),
        Account(code='1-2000', name='Aset Tetap', category='ASET', normal_balance='debit'),
        Account(code='1-2100', name='Akumulasi Penyusutan', category='ASET', normal_balance='credit'),
        Account(code='2-1000', name='Utang Usaha', category='KEWAJIBAN', normal_balance='credit'),
        Account(code='3-1000', name='Modal Pemilik', category='MODAL', normal_balance='credit'),
        Account(code='3-2000', name='Prive', category='MODAL', normal_balance='debit'),
        Account(code='4-1000', name='Penjualan', category='PENDAPATAN', normal_balance='credit'),
        Account(code='5-1000', name='Harga Pokok Penjualan', category='HPP', normal_balance='debit'),
        Account(code='6-1000', name='Beban Gaji', category='BEBAN', normal_balance='debit'),
        Account(code='6-2000', name='Beban Listrik & Air', category='BEBAN', normal_balance='debit'),
        Account(code='6-3000', name='Beban Penyusutan', category='BEBAN', normal_balance='debit'),
        Account(code='6-4000', name='Beban Sewa', category='BEBAN', normal_balance='debit'),
        Account(code='6-5000', name='Beban Lain-lain', category='BEBAN', normal_balance='debit'),
    ]
    db.session.bulk_save_objects(initial_accounts)
    
    # 3. Seed Product Dummy
    if not Product.query.first():
        p = Product(code='ITM-001', name='Pakan Standar', qty=0, avg_cost=0)
        db.session.add(p)
        
    db.session.commit()
    print("Database Seeded.")

# --- ROUTES AUTH ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('form_type') == 'login':
        email = request.form['email'] # Login pakai email/username
        password = request.form['password']
        
        user = User.query.filter((User.email==email) | (User.username==email)).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Email atau Password Salah")

    if request.method == 'POST' and request.form.get('form_type') == 'register':
        email = request.form['email']
        username = request.form['new_username']
        password = request.form['new_password']
        
        if User.query.filter((User.email==email) | (User.username==username)).first():
             return render_template('login.html', error="Email/Username sudah terdaftar!")

        new_user = User(email=email, username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return render_template('login.html', success="Registrasi Sukses! Silakan Login.")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('dashboard.html', username=session['username'])

# --- API ACCOUNTS ---
@app.route('/api/accounts', methods=['GET', 'POST'])
def handle_accounts():
    if request.method == 'POST':
        data = request.json
        try:
            new_acc = Account(code=data['code'], name=data['name'], category=data['category'], normal_balance=data['normal_balance'])
            db.session.add(new_acc)
            db.session.commit()
            return jsonify({'msg': 'Akun berhasil dibuat'})
        except Exception as e: return jsonify({'error': str(e)}), 400
    
    accounts = Account.query.order_by(Account.code).all()
    return jsonify([a.to_dict() for a in accounts])

@app.route('/api/accounts/<int:id>', methods=['PUT', 'DELETE'])
def single_account(id):
    acc = Account.query.get(id)
    if not acc: return jsonify({'error': '404'}), 404
    if request.method == 'DELETE':
        db.session.delete(acc)
        db.session.commit()
        return jsonify({'msg': 'Deleted'})
    if request.method == 'PUT':
        d = request.json
        acc.code = d['code']; acc.name = d['name']; acc.category = d['category']; acc.normal_balance = d['normal_balance']
        db.session.commit()
        return jsonify({'msg': 'Updated'})

# --- API PRODUCTS (INVENTORY) ---
@app.route('/api/products', methods=['GET', 'POST'])
def handle_products():
    if request.method == 'GET':
        prods = Product.query.all()
        return jsonify([p.to_dict() for p in prods])
    if request.method == 'POST':
        d = request.json
        try:
            # Jika ada 'adjustment' (dari transaksi pembelian/penjualan manual)
            # Ini logic Moving Average Sederhana
            if 'transaction_type' in d:
                prod = Product.query.get(d['id'])
                qty = float(d['qty'])
                total_price = float(d['total_price']) # Total harga beli
                
                if d['transaction_type'] == 'purchase':
                    # Moving Average: (Nilai Lama + Nilai Baru) / (Qty Lama + Qty Baru)
                    old_val = prod.qty * prod.avg_cost
                    new_val = old_val + total_price
                    new_qty = prod.qty + qty
                    prod.avg_cost = new_val / new_qty if new_qty > 0 else 0
                    prod.qty = new_qty
                
                elif d['transaction_type'] == 'sale':
                    # Penjualan mengurangi qty, avg_cost tetap
                    prod.qty -= qty
                
                db.session.commit()
                return jsonify({'msg': 'Stok Terupdate', 'avg_cost': prod.avg_cost})
            
            # Tambah Produk Baru
            else:
                new_p = Product(code=d['code'], name=d['name'], qty=d['qty'], avg_cost=d['cost'])
                db.session.add(new_p)
                db.session.commit()
                return jsonify({'msg': 'Produk dibuat'})
        except Exception as e: return jsonify({'error': str(e)}), 400

# --- API TRANSAKSI ---
@app.route('/api/transactions', methods=['GET', 'POST'])
def handle_transactions():
    if request.method == 'POST':
        try:
            date_val = datetime.strptime(request.form['date'], '%Y-%m-%d')
            desc = request.form['description']
            t_type = request.form.get('type', 'Umum')
            
            due_date = None
            if request.form.get('due_date'):
                due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d')

            filename = None
            if 'proof' in request.files:
                file = request.files['proof']
                if file.filename != '':
                    filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            new_trans = Transaction(date=date_val, due_date=due_date, description=desc, type=t_type, proof_file=filename)
            db.session.add(new_trans)
            db.session.flush()

            lines = json.loads(request.form['lines_json'])
            for line in lines:
                db.session.add(JournalEntry(
                    transaction_id=new_trans.id, 
                    account_id=line['accountId'],
                    debit=float(line['debit']), 
                    credit=float(line['credit']), 
                    sub_ledger_name=line.get('subName', '')
                ))
            
            # --- LOGIC MOVING AVERAGE INTEGRATION ---
            # Jika user kirim data inventory (dari form khusus inventory di front end)
            inventory_data = request.form.get('inventory_json')
            if inventory_data:
                inv_items = json.loads(inventory_data)
                for item in inv_items:
                    prod = Product.query.get(item['product_id'])
                    qty = float(item['qty'])
                    total = float(item['total']) # Total Harga Beli (jika beli)
                    
                    if t_type == 'Pembelian': # Menambah stok, update rata-rata
                        old_val = prod.qty * prod.avg_cost
                        new_val = old_val + total
                        new_qty = prod.qty + qty
                        prod.avg_cost = new_val / new_qty if new_qty > 0 else 0
                        prod.qty = new_qty
                    elif t_type == 'Penjualan': # Mengurangi stok
                        prod.qty -= qty
                        # HPP otomatis sudah di jurnal oleh frontend atau user manual
            
            db.session.commit()
            return jsonify({'msg': 'Sukses'})
        except Exception as e: 
            return jsonify({'error': str(e)}), 500

    # GET Transactions with Filter
    start = request.args.get('start')
    end = request.args.get('end')
    query = Transaction.query.order_by(Transaction.date.desc(), Transaction.id.desc())
    
    if start and end:
        s_date = datetime.strptime(start, '%Y-%m-%d')
        e_date = datetime.strptime(end, '%Y-%m-%d')
        query = query.filter(Transaction.date.between(s_date, e_date))
        
    trans = query.all()
    return jsonify([t.to_dict() for t in trans])

@app.route('/api/transactions/<int:id>', methods=['GET', 'DELETE'])
def manage_trans(id):
    trans = Transaction.query.get(id)
    if not trans: return jsonify({'error': '404'}), 404
    if request.method == 'GET': return jsonify(trans.to_dict())
    if request.method == 'DELETE':
        db.session.delete(trans)
        db.session.commit()
        return jsonify({'msg': 'Deleted'})

# --- API LAPORAN LENGKAP ---
@app.route('/api/reports/all')
def financial_report():
    start = request.args.get('start')
    end = request.args.get('end')
    
    # Query Jurnal Entries berdasarkan tanggal
    query = JournalEntry.query.join(Transaction)
    if start and end:
        s_date = datetime.strptime(start, '%Y-%m-%d').date()
        e_date = datetime.strptime(end, '%Y-%m-%d').date()
        query = query.filter(Transaction.date.between(s_date, e_date))
    
    entries = query.all()
    
    ledger = {}
    ap_ledger = {} # Utang
    ar_ledger = {} # Piutang
    summary = {'income':0, 'expense':0, 'cogs':0, 'asset':0, 'liability':0, 'equity':0}
    
    # Grafik Data (Income/Expense per bulan)
    chart_data = {'labels': [], 'income': [], 'expense': []}
    monthly_agg = {} # key: "YYYY-MM", val: {inc:0, exp:0}

    # 1. Proses Laba Rugi & Buku Besar (Berdasarkan Range Waktu)
    for e in entries:
        cat = e.account.category
        val = (e.debit - e.credit) if e.account.normal_balance == 'debit' else (e.credit - e.debit)
        
        # Ledger Utama
        if e.account_id not in ledger:
            ledger[e.account_id] = {'id':e.account_id, 'code':e.account.code, 'name':e.account.name, 'category':cat, 'balance':0, 'entries':[]}
        ledger[e.account_id]['balance'] += val
        ledger[e.account_id]['entries'].append({'date':e.transaction.date.strftime('%Y-%m-%d'), 'desc':e.transaction.description, 'debit':e.debit, 'credit':e.credit})

        # Kalkulasi Laba Rugi
        if cat == 'PENDAPATAN': summary['income'] += e.credit
        elif cat == 'BEBAN': summary['expense'] += e.debit
        elif cat == 'HPP': summary['cogs'] += e.debit
        
        # Grafik Aggregation
        m_key = e.transaction.date.strftime('%Y-%m')
        if m_key not in monthly_agg: monthly_agg[m_key] = {'inc':0, 'exp':0}
        if cat == 'PENDAPATAN': monthly_agg[m_key]['inc'] += e.credit
        if cat in ['BEBAN', 'HPP']: monthly_agg[m_key]['exp'] += e.debit

        # Buku Pembantu (Subsidiary)
        if e.sub_ledger_name:
            item = {'date':e.transaction.date.strftime('%Y-%m-%d'), 'desc':e.transaction.description, 'debit':e.debit, 'credit':e.credit, 'due': e.transaction.due_date.strftime('%Y-%m-%d') if e.transaction.due_date else '-'}
            
            if e.account.code == '2-1000': # Utang
                if e.sub_ledger_name not in ap_ledger: ap_ledger[e.sub_ledger_name] = {'balance':0, 'entries':[]}
                ap_ledger[e.sub_ledger_name]['balance'] += (e.credit - e.debit)
                ap_ledger[e.sub_ledger_name]['entries'].append(item)
                
            elif e.account.code == '1-1200': # Piutang
                if e.sub_ledger_name not in ar_ledger: ar_ledger[e.sub_ledger_name] = {'balance':0, 'entries':[]}
                ar_ledger[e.sub_ledger_name]['balance'] += (e.debit - e.credit)
                ar_ledger[e.sub_ledger_name]['entries'].append(item)

    # Sort Chart Data
    sorted_keys = sorted(monthly_agg.keys())
    chart_data['labels'] = sorted_keys
    chart_data['income'] = [monthly_agg[k]['inc'] for k in sorted_keys]
    chart_data['expense'] = [monthly_agg[k]['exp'] for k in sorted_keys]

    net_profit = summary['income'] - (summary['expense'] + summary['cogs'])
    
    # 2. Proses Neraca (Harus Saldo Kumulatif dari AWAL WAKTU sampai END DATE)
    # Kita query ulang untuk Aset, Kewajiban, Modal tanpa start_date filter, tapi dibatasi end_date
    bs_query = JournalEntry.query.join(Transaction)
    if end:
        bs_end = datetime.strptime(end, '%Y-%m-%d').date()
        bs_query = bs_query.filter(Transaction.date <= bs_end)
    
    bs_entries = bs_query.all()
    for e in bs_entries:
        cat = e.account.category
        if cat == 'ASET': summary['asset'] += (e.debit - e.credit)
        elif cat == 'KEWAJIBAN': summary['liability'] += (e.credit - e.debit)
        elif cat == 'MODAL': summary['equity'] += (e.credit - e.debit)
    
    return jsonify({
        'summary': summary,
        'net_profit': net_profit,
        'ledger': list(ledger.values()),
        'ap_ledger': ap_ledger,
        'ar_ledger': ar_ledger,
        'chart': chart_data
    })

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    app.run(debug=True, port=5000)
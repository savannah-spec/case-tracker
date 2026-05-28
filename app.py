from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import User

from pypdf import PdfReader
from docx import Document
import os
from openai import OpenAI

from flask import Flask, request, redirect, render_template, Response
from models import (
    db,
    Case,
    Task,
    User,
    CalendarEvent,
    Contact,
    Client,
    TimeEntry,
    Invoice,
    TrustPayment,
    TrustLedgerEntry,
    BillingRate
    CaseDocument
)
import csv
import io
import json

from datetime import datetime

from decimal import Decimal, ROUND_HALF_UP

from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-this")
client = None

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///cases.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def split_client_name(client_name):
    if not client_name:
        return "", ""

    cleaned_name = " ".join(client_name.strip().split())

    if not cleaned_name:
        return "", ""

    # Handles names entered as "Last, First"
    if "," in cleaned_name:
        parts = cleaned_name.split(",", 1)
        last_name = parts[0].strip()
        first_name = parts[1].strip()
        return first_name, last_name

    # Handles names entered as "First Last"
    parts = cleaned_name.split(" ", 1)

    if len(parts) == 1:
        return parts[0], ""

    return parts[0], parts[1]


def sync_client_contact_for_case(case):
    client_name = (case.client_name or "").strip()

    if not client_name:
        return None

    first_name, last_name = split_client_name(client_name)

    existing_contact = Contact.query.filter_by(
        case_id=case.id,
        contact_role="Client"
    ).first()

    if existing_contact:
        existing_contact.contact_type = "Client"
        existing_contact.first_name = first_name
        existing_contact.last_name = last_name
        existing_contact.company_name = ""
        existing_contact.contact_group = "Clients"
        existing_contact.contact_role = "Client"
        existing_contact.archived = False

        if not existing_contact.notes:
            existing_contact.notes = "Created automatically from matter client name."

        return existing_contact

    contact = Contact(
        contact_type="Client",
        first_name=first_name,
        last_name=last_name,
        company_name="",
        email="",
        phone="",
        address="",
        contact_group="Clients",
        contact_role="Client",
        case_id=case.id,
        notes="Created automatically from matter client name.",
        archived=False
    )

    db.session.add(contact)

    return contact

def ensure_admin_user():
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    admin_name = os.environ.get("ADMIN_NAME", "Admin")

    if not admin_email or not admin_password:
        return

    user = User.query.filter_by(email=admin_email).first()

    if user:
        user.name = admin_name
        user.role = "admin"
        user.password_hash = generate_password_hash(admin_password)
    else:
        user = User(
            name=admin_name,
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            role="admin"
        )
        db.session.add(user)

    db.session.commit()

@app.route("/setup_admin", methods=["GET", "POST"])
def setup_admin():
    existing_user = User.query.first()

    if existing_user:
        return redirect("/login")

    if request.method == "POST":
        user = User(
            name=request.form["name"],
            email=request.form["email"],
            password_hash=generate_password_hash(request.form["password"]),
            role="admin"
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect("/")

    return """
    <h1>Create Admin Account</h1>
    <form method="POST">
        <p>Name</p><input name="name">
        <p>Email</p><input name="email">
        <p>Password</p><input name="password" type="password">
        <br><br>
        <button>Create Admin</button>
    </form>
    """


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        user = User.query.filter_by(email=request.form["email"]).first()

        if user and check_password_hash(user.password_hash, request.form["password"]):
            login_user(user)
            return redirect("/")

        return "Invalid login. <br><a href='/login'>Try again</a>"

    return """
    <h1>Login</h1>
    <form method="POST">
        <p>Email</p><input name="email">
        <p>Password</p><input name="password" type="password">
        <br><br>
        <button>Login</button>
    </form>
    """


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/login")

@app.route("/")
@login_required
def home():
    cases = Case.query.all()

    total_cases = Case.query.count()

    open_tasks = Task.query.filter_by(completed=False).count()

    return render_template(
        "dashboard.html",
        cases=cases,
        total_cases=total_cases,
        open_tasks=open_tasks
    )


@app.route("/setup")
def setup():
    db.create_all()
    return "Database created!"


@app.route("/upload_csv", methods=["POST"])
def upload_csv():
    file = request.files.get("csv_file")

    if not file:
        return "No file uploaded"

    stream = io.StringIO(file.stream.read().decode("utf-8-sig"))

    sample = stream.read(2048)
    stream.seek(0)

    dialect = csv.Sniffer().sniff(sample)
    reader = csv.DictReader(stream, dialect=dialect)

    added_count = 0
    updated_count = 0

    for row in reader:
        mycase_id = row.get("MyCase ID")
        case_number = row.get("Number")
        case_name = row.get("Case/Matter Name")
        client_name = row.get("Contacts") or row.get("Billing Contact")
        stage = row.get("Case Stage")
        status = "Closed" if row.get("Case Closed") == "Yes" else "Open"

        if not mycase_id:
            continue

        existing_case = Case.query.filter_by(mycase_id=mycase_id).first()

        if existing_case:
            existing_case.case_number = case_number
            existing_case.case_name = case_name
            existing_case.client_name = client_name
            existing_case.stage = stage
            existing_case.status = status

            sync_client_contact_for_case(existing_case)
            link_case_to_client(existing_case)
            refresh_case_financials(existing_case)

            updated_count += 1
        else:
            new_case = Case(
                mycase_id=mycase_id,
                case_number=case_number,
                case_name=case_name,
                client_name=client_name,
                stage=stage,
                status=status
            )

            db.session.add(new_case)
            db.session.flush()

            sync_client_contact_for_case(new_case)
            link_case_to_client(new_case)
            refresh_case_financials(new_case)
            
            added_count += 1

    db.session.commit()

    return f"""
    Upload complete.<br>
    Added: {added_count}<br>
    Updated: {updated_count}<br>
    <a href="/">Back</a>
    """


@app.route("/update_document_source/<int:case_id>", methods=["POST"])
def update_document_source(case_id):
    case = Case.query.get_or_404(case_id)
    case.document_location = request.form.get("document_location")
    db.session.commit()
    return redirect("/")


@app.route("/summarize_case/<int:case_id>", methods=["POST"])
def summarize_case(case_id):
    case = Case.query.get_or_404(case_id)

    folder_path = case.document_location

    if not folder_path:
        return "No folder path set. <br><a href='/'>Back</a>"

    if not os.path.isdir(folder_path):
        return f"Folder not found: {folder_path}<br><a href='/'>Back</a>"

    combined_text = ""

    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)

        try:
            if filename.lower().endswith(".txt"):
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    combined_text += f"\n\n--- {filename} ---\n" + f.read()

            elif filename.lower().endswith(".pdf"):
                reader = PdfReader(file_path)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() or ""
                combined_text += f"\n\n--- {filename} ---\n{text}"

            elif filename.lower().endswith(".docx"):
                doc = Document(file_path)
                text = "\n".join([p.text for p in doc.paragraphs])
                combined_text += f"\n\n--- {filename} ---\n{text}"

        except Exception:
            combined_text += f"\n\n--- {filename} (ERROR READING FILE) ---\n"

    if not combined_text.strip():
        return "No readable documents found. <br><a href='/'>Back</a>"

    prompt = f"""
You are assisting a law firm.

Analyze the following case documents and return a structured JSON response.

Case Info:
- Case Name: {case.case_name}
- Client: {case.client_name}
- Case Number: {case.case_number}
- Stage: {case.stage}

Return JSON with:
{{
  "summary": "...",
  "key_facts": ["...", "..."],
  "deadlines": ["...", "..."],
  "tasks": ["...", "..."],
  "risks": ["...", "..."]
}}

Documents:
{combined_text[:50000]}
"""

    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        return "Missing OPENAI_API_KEY on Render. Add it under Environment Variables. <br><a href='/'>Back</a>"

    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    try:
        parsed = json.loads(response.output_text)
        case.summary = json.dumps(parsed, indent=2)

        old_tasks = Task.query.filter_by(case_id=case.id).all()
        for old_task in old_tasks:
            db.session.delete(old_task)

        tasks = parsed.get("tasks", [])

        for task_text in tasks:
            new_task = Task(
                case_id=case.id,
                description=task_text,
                completed=False
            )
            db.session.add(new_task)

    except:
        case.summary = response.output_text

    db.session.commit()

    return redirect("/")


@app.route("/toggle_task/<int:task_id>", methods=["POST"])
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    task.completed = not task.completed
    db.session.commit()
    return redirect("/")

@app.route("/matter/<int:case_id>")
@login_required
def matter_detail(case_id):
    case = Case.query.get_or_404(case_id)

    tasks = Task.query.filter_by(
        case_id=case.id,
        parent_task_id=None
    ).all()

    subtasks = Task.query.filter(
        Task.case_id == case.id,
        Task.parent_task_id != None
    ).all()

    subtasks_by_parent = {}

    for subtask in subtasks:
        if subtask.parent_task_id not in subtasks_by_parent:
            subtasks_by_parent[subtask.parent_task_id] = []

        subtasks_by_parent[subtask.parent_task_id].append(subtask)

    users = User.query.all()

    return render_template(
        "matter_detail.html",
        case=case,
        tasks=tasks,
        subtasks_by_parent=subtasks_by_parent,
        users=users
    )

@app.route("/add_case_manual", methods=["POST"])
@login_required
def add_case_manual():
    new_case = Case(
        mycase_id="manual-" + str(int(__import__("time").time())),
        case_name=request.form.get("case_name"),
        client_name=request.form.get("client_name"),
        case_number=request.form.get("case_number"),
        stage=request.form.get("stage"),
        status=request.form.get("status") or "Open"
    )

    db.session.add(new_case)
    db.session.flush()

    sync_client_contact_for_case(new_case)
    link_case_to_client(new_case)
    refresh_case_financials(new_case)

    db.session.commit()

    return redirect("/")

@app.route("/matter/<int:case_id>/add_task", methods=["POST"])
@login_required
def add_task(case_id):
    task = Task(
        case_id=case_id,
        parent_task_id=None,
        assigned_to_id=request.form.get("assigned_to_id") or None,
        title=request.form.get("title"),
        description=request.form.get("description"),
        due_date=request.form.get("due_date"),
        priority=request.form.get("priority") or "Normal",
        status=request.form.get("status") or "Not Started",
        completed=False
    )

    db.session.add(task)
    db.session.commit()

    return redirect(f"/matter/{case_id}")

@app.route("/task/<int:task_id>/add_subtask", methods=["POST"])
@login_required
def add_subtask(task_id):
    parent = Task.query.get_or_404(task_id)

    subtask = Task(
        case_id=parent.case_id,
        parent_task_id=parent.id,
        assigned_to_id=parent.assigned_to_id,
        title=request.form.get("title"),
        description="",
        due_date=parent.due_date,
        priority=parent.priority,
        status="Not Started",
        completed=False
    )

    db.session.add(subtask)
    db.session.commit()

    return redirect(f"/matter/{parent.case_id}")

@app.route("/admin/users", methods=["GET", "POST"])
@login_required
def admin_users():
    if current_user.role != "admin":
        return "Access denied"

    if request.method == "POST":
        new_user = User(
            name=request.form.get("name"),
            email=request.form.get("email"),
            password_hash=generate_password_hash(request.form.get("password")),
            role=request.form.get("role") or "staff"
        )

        db.session.add(new_user)
        db.session.commit()

        return redirect("/admin/users")

    users = User.query.all()

    html = """
    <h1>User Management</h1>
    <p><a href="/">Back to Dashboard</a></p>

    <h2>Add User</h2>
    <form method="POST">
        <p>Name</p>
        <input name="name">

        <p>Email</p>
        <input name="email">

        <p>Password</p>
        <input name="password" type="password">

        <p>Role</p>
        <select name="role">
            <option value="admin">Admin</option>
            <option value="attorney">Attorney</option>
            <option value="staff">Staff</option>
            <option value="paralegal">Paralegal</option>
        </select>

        <br><br>
        <button>Add User</button>
    </form>

    <h2>Existing Users</h2>
    """

    for user in users:
        html += f"""
        <div style="border:1px solid #ccc; padding:10px; margin:10px;">
            <strong>{user.name}</strong><br>
            {user.email}<br>
            Role: {user.role}
        </div>
        """

    return html

@app.route("/matters", methods=["GET", "POST"])
@login_required
def matters():
    if request.method == "POST":
        new_case = Case(
            mycase_id="manual-" + str(int(__import__("time").time())),
            case_name=request.form.get("case_name"),
            client_name=request.form.get("client_name"),
            case_number=request.form.get("case_number"),
            stage=request.form.get("stage"),
            status=request.form.get("status") or "Open"
        )

        db.session.add(new_case)
        db.session.flush()

        sync_client_contact_for_case(new_case)
        link_case_to_client(new_case)
        refresh_case_financials(new_case)

        db.session.commit()

        return redirect("/matters")

    q = request.args.get("q")

    if q:
        cases = Case.query.filter(
            Case.case_name.contains(q) |
            Case.client_name.contains(q) |
            Case.case_number.contains(q)
        ).all()
    else:
        cases = Case.query.all()

    return render_template(
        "matters.html",
        cases=cases,
        q=q
    )

@app.route("/matters/new", methods=["GET", "POST"])
@login_required
def new_matter():
    if request.method == "POST":
        new_case = Case(
            mycase_id="manual-" + str(int(__import__("time").time())),
            case_name=request.form.get("case_name"),
            client_name=request.form.get("client_name"),
            case_number=request.form.get("case_number"),
            stage=request.form.get("stage"),
            status=request.form.get("status") or "Open"
        )

        db.session.add(new_case)
        db.session.flush()

        sync_client_contact_for_case(new_case)
        link_case_to_client(new_case)
        refresh_case_financials(new_case)

        db.session.commit()

        return redirect("/matters")

    return render_template("add_matter.html")

@app.route("/tasks", methods=["GET"])
@login_required
def tasks():
    parent_tasks = Task.query.filter_by(parent_task_id=None).all()

    subtasks = Task.query.filter(
        Task.parent_task_id != None
    ).all()

    subtasks_by_parent = {}

    for subtask in subtasks:
        if subtask.parent_task_id not in subtasks_by_parent:
            subtasks_by_parent[subtask.parent_task_id] = []

        subtasks_by_parent[subtask.parent_task_id].append(subtask)

    cases = Case.query.all()
    users = User.query.all()

    case_names = {}
    for case in cases:
        case_names[case.id] = case.case_name

    user_names = {}
    for user in users:
        user_names[user.id] = user.name

    return render_template(
        "tasks.html",
        tasks=parent_tasks,
        subtasks_by_parent=subtasks_by_parent,
        case_names=case_names,
        user_names=user_names
    )


@app.route("/tasks/new", methods=["GET", "POST"])
@login_required
def new_task():
    cases = Case.query.all()
    users = User.query.all()

    if request.method == "POST":
        case_id = request.form.get("case_id") or None
        assigned_to_id = request.form.get("assigned_to_id") or None

        parent_task = Task(
            case_id=int(case_id) if case_id else None,
            parent_task_id=None,
            assigned_to_id=int(assigned_to_id) if assigned_to_id else None,
            title=request.form.get("title"),
            description=request.form.get("description"),
            due_date=request.form.get("due_date"),
            priority=request.form.get("priority") or "Normal",
            status=request.form.get("status") or "Not Started",
            completed=False
        )

        db.session.add(parent_task)
        db.session.commit()

        subtask_titles = request.form.getlist("subtasks[]")

        for subtask_title in subtask_titles:
            if subtask_title.strip():
                subtask = Task(
                    case_id=parent_task.case_id,
                    parent_task_id=parent_task.id,
                    assigned_to_id=parent_task.assigned_to_id,
                    title=subtask_title.strip(),
                    description="",
                    due_date=None,
                    priority=parent_task.priority,
                    status="Not Started",
                    completed=False
                )

                db.session.add(subtask)

        db.session.commit()

        return redirect("/tasks")

    return render_template(
        "add_task.html",
        cases=cases,
        users=users
    )

def parse_float(value, default=0):
    try:
        if value is None or value == "":
            return default

        cleaned = str(value).replace("$", "").replace(",", "").strip()

        if cleaned == "":
            return default

        return float(cleaned)
    except Exception:
        return default

def money(value):
    if value is None or value == "":
        return Decimal("0.00")

    cleaned = str(value).replace("$", "").replace(",", "").strip()

    if cleaned == "":
        return Decimal("0.00")

    return Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def normalize_text(value):
    return " ".join(str(value or "").strip().split())


def make_reference(prefix):
    return prefix + "-" + str(int(__import__("time").time()))


def get_or_create_client_from_name(client_name):
    cleaned_name = normalize_text(client_name)

    if not cleaned_name:
        return None

    client = Client.query.filter_by(client_name=cleaned_name).first()

    if client:
        return client

    client = Client(
        client_name=cleaned_name,
        client_type="Individual",
        status="Active",
        client_notes="Created automatically from matter/client import."
    )

    db.session.add(client)
    db.session.flush()

    return client


def link_case_to_client(case):
    if not case:
        return None

    if case.client_id:
        return Client.query.get(case.client_id)

    client = get_or_create_client_from_name(case.client_name)

    if client:
        case.client_id = client.id

    return client


def trust_entry_signed_amount(entry):
    amount = abs(parse_float(entry.amount))

    positive_types = [
        "Deposit",
        "Trust Payment"
    ]

    negative_types = [
        "Withdrawal",
        "Earned Fee Transfer",
        "Refund",
        "Adjustment"
    ]

    if entry.transaction_type in positive_types:
        return amount

    if entry.transaction_type in negative_types:
        return -amount

    return parse_float(entry.amount)


def calculate_case_trust_balance(case_id):
    entries = TrustLedgerEntry.query.filter_by(case_id=case_id).all()

    balance = 0

    for entry in entries:
        balance += trust_entry_signed_amount(entry)

    return round(balance, 2)


def update_case_trust_status(case):
    if not case:
        return None

    balance = calculate_case_trust_balance(case.id)
    case.trust_balance = balance

    minimum = parse_float(case.minimum_trust_threshold)

    if balance < 0:
        case.trust_status = "Negative Balance"
    elif minimum and balance < minimum:
        case.trust_status = "Replenishment Needed"
    elif balance <= 0:
        case.trust_status = "Low Balance"
    else:
        case.trust_status = "Adequately Funded"

    return case.trust_status


def update_case_billing_summary(case):
    if not case:
        return None

    time_entries = TimeEntry.query.filter_by(case_id=case.id).all()
    invoices = Invoice.query.filter_by(case_id=case.id).all()
    expenses = Expense.query.filter_by(case_id=case.id).all()
    
    total_hours = 0
    billable_hours = 0
    non_billable_hours = 0

    for entry in time_entries:
        hours = parse_float(entry.hours_worked)
        total_hours += hours

        if entry.billable_status == "Billable":
            billable_hours += hours
        else:
            non_billable_hours += hours

    total_billed = 0
    total_paid = 0

    for invoice in invoices:
        total_billed += parse_float(invoice.total_amount)
        total_paid += parse_float(invoice.amount_paid)

    case.total_hours_worked = round(total_hours, 2)
    case.billable_hours = round(billable_hours, 2)
    case.non_billable_hours = round(non_billable_hours, 2)

    case.total_amount_billed = float(money(total_billed))
    case.total_trust_applied_to_balance = float(money(total_applied))
    case.total_amount_paid = float(money(total_paid))

    outstanding_amount = (
        money(total_billed)
        - money(total_applied)
        - money(total_paid)
    )
    
    case.outstanding_ar = float(outstanding_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    case.total_expenses = round(total_expenses, 2)
    case.unbilled_amount = round(
        sum(
            parse_float(entry.total_amount)
            for entry in time_entries
            if entry.invoice_status == "Not Invoiced"
        ) +
        sum(
            parse_float(expense.amount)
            for expense in expenses
            if expense.invoice_status == "Not Invoiced"
        ),
        2
    )

    if billable_hours:
        case.effective_hourly_value = round(total_billed / billable_hours, 2)
    else:
        case.effective_hourly_value = 0

    return case


def refresh_case_financials(case):
    if not case:
        return None

    link_case_to_client(case)
    update_case_trust_status(case)
    update_case_billing_summary(case)

    return case
    
def csv_response(filename, headers, rows):
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(headers)

    for row in rows:
        writer.writerow(row)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )

@app.route("/calendar", methods=["GET"])
@login_required
def calendar():
    view = request.args.get("view") or "Agenda"
    staff_id = request.args.get("staff_id") or None
    case_id = request.args.get("case_id") or None
    event_type = request.args.get("event_type") or None

    event_query = CalendarEvent.query

    if staff_id:
        event_query = event_query.filter_by(assigned_user_id=int(staff_id))

    if case_id:
        event_query = event_query.filter_by(case_id=int(case_id))

    if event_type:
        event_query = event_query.filter_by(event_type=event_type)

    events = event_query.order_by(
        CalendarEvent.event_date.asc(),
        CalendarEvent.start_time.asc()
    ).all()

    task_query = Task.query.filter(
        Task.due_date.isnot(None),
        Task.parent_task_id.is_(None)
    )

    if staff_id:
        task_query = task_query.filter_by(assigned_to_id=int(staff_id))

    if case_id:
        task_query = task_query.filter_by(case_id=int(case_id))

    tasks_due = task_query.order_by(Task.due_date.asc()).all()

    cases = Case.query.order_by(Case.case_name.asc()).all()
    users = User.query.order_by(User.name.asc()).all()

    event_types = [
        "Court Appearance",
        "Deadline",
        "Meeting",
        "Staff Meeting",
        "Client Meeting",
        "Deposition",
        "Hearing",
        "Trial",
        "Reminder",
        "Other"
    ]

    return render_template(
        "calendar.html",
        events=events,
        tasks_due=tasks_due,
        cases=cases,
        users=users,
        event_types=event_types,
        view=view,
        selected_staff_id=staff_id,
        selected_case_id=case_id,
        selected_event_type=event_type
    )


@app.route("/calendar/new", methods=["GET", "POST"])
@login_required
def new_calendar_event():
    cases = Case.query.order_by(Case.case_name.asc()).all()
    users = User.query.order_by(User.name.asc()).all()

    event_types = [
        "Court Appearance",
        "Deadline",
        "Meeting",
        "Staff Meeting",
        "Client Meeting",
        "Deposition",
        "Hearing",
        "Trial",
        "Reminder",
        "Other"
    ]

    repeat_options = [
        "Does not repeat",
        "Daily",
        "Weekly",
        "Monthly",
        "Yearly"
    ]

    if request.method == "POST":
        case_id = request.form.get("case_id") or None

        if request.form.get("not_linked"):
            case_id = None

        assigned_user_id = request.form.get("assigned_user_id") or None
        reminder_minutes = request.form.get("reminder_minutes") or None

        event = CalendarEvent(
            title=request.form.get("title"),
            event_type=request.form.get("event_type") or "Event",
            case_id=int(case_id) if case_id else None,
            assigned_user_id=int(assigned_user_id) if assigned_user_id else None,
            created_by_user_id=current_user.id,
            event_date=request.form.get("event_date"),
            start_time=request.form.get("start_time"),
            end_time=request.form.get("end_time"),
            all_day=True if request.form.get("all_day") else False,
            repeats=request.form.get("repeats") or "Does not repeat",
            location=request.form.get("location"),
            description=request.form.get("description"),
            reminder_method=request.form.get("reminder_method") or "None",
            reminder_minutes=int(reminder_minutes) if reminder_minutes else None,
            is_private=True if request.form.get("is_private") else False
        )

        db.session.add(event)
        db.session.commit()

        return redirect("/calendar")

    return render_template(
        "calendar_event_form.html",
        event=None,
        action_url="/calendar/new",
        cases=cases,
        users=users,
        event_types=event_types,
        repeat_options=repeat_options
    )


@app.route("/calendar/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_calendar_event(event_id):
    event = CalendarEvent.query.get_or_404(event_id)

    cases = Case.query.order_by(Case.case_name.asc()).all()
    users = User.query.order_by(User.name.asc()).all()

    event_types = [
        "Court Appearance",
        "Deadline",
        "Meeting",
        "Staff Meeting",
        "Client Meeting",
        "Deposition",
        "Hearing",
        "Trial",
        "Reminder",
        "Other"
    ]

    repeat_options = [
        "Does not repeat",
        "Daily",
        "Weekly",
        "Monthly",
        "Yearly"
    ]

    if request.method == "POST":
        case_id = request.form.get("case_id") or None

        if request.form.get("not_linked"):
            case_id = None

        assigned_user_id = request.form.get("assigned_user_id") or None
        reminder_minutes = request.form.get("reminder_minutes") or None

        event.title = request.form.get("title")
        event.event_type = request.form.get("event_type") or "Event"
        event.case_id = int(case_id) if case_id else None
        event.assigned_user_id = int(assigned_user_id) if assigned_user_id else None
        event.event_date = request.form.get("event_date")
        event.start_time = request.form.get("start_time")
        event.end_time = request.form.get("end_time")
        event.all_day = True if request.form.get("all_day") else False
        event.repeats = request.form.get("repeats") or "Does not repeat"
        event.location = request.form.get("location")
        event.description = request.form.get("description")
        event.reminder_method = request.form.get("reminder_method") or "None"
        event.reminder_minutes = int(reminder_minutes) if reminder_minutes else None
        event.is_private = True if request.form.get("is_private") else False

        db.session.commit()

        return redirect("/calendar")

    return render_template(
        "calendar_event_form.html",
        event=event,
        action_url=f"/calendar/{event.id}/edit",
        cases=cases,
        users=users,
        event_types=event_types,
        repeat_options=repeat_options
    )


@app.route("/calendar/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_calendar_event(event_id):
    event = CalendarEvent.query.get_or_404(event_id)

    db.session.delete(event)
    db.session.commit()

    return redirect("/calendar")


@app.route("/contacts", methods=["GET", "POST"])
@login_required
def contacts():
    cases = Case.query.order_by(Case.case_name.asc()).all()

    if request.method == "POST":
        contact = Contact(
            contact_type=request.form.get("contact_type") or "Person",
            first_name=request.form.get("first_name"),
            last_name=request.form.get("last_name"),
            company_name=request.form.get("company_name"),
            email=request.form.get("email"),
            phone=request.form.get("phone"),
            address=request.form.get("address"),
            contact_group=request.form.get("contact_group"),
            contact_role=request.form.get("contact_role"),
            case_id=int(request.form.get("case_id")) if request.form.get("case_id") else None,
            notes=request.form.get("notes"),
            archived=False
        )

        db.session.add(contact)
        db.session.commit()

        return redirect("/contacts")

    q = request.args.get("q") or None
    show_archived = True if request.args.get("archived") == "1" else False

    contact_query = Contact.query

    if not show_archived:
        contact_query = contact_query.filter_by(archived=False)

    if q:
        contact_query = contact_query.filter(
            Contact.first_name.contains(q) |
            Contact.last_name.contains(q) |
            Contact.company_name.contains(q) |
            Contact.email.contains(q) |
            Contact.phone.contains(q)
        )

    contacts = contact_query.order_by(
        Contact.last_name.asc(),
        Contact.first_name.asc(),
        Contact.company_name.asc()
    ).all()

    return render_template(
        "contacts.html",
        contacts=contacts,
        cases=cases,
        q=q,
        show_archived=show_archived
    )


@app.route("/contact/<int:contact_id>/archive", methods=["POST"])
@login_required
def archive_contact(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    contact.archived = True

    db.session.commit()

    return redirect("/contacts")


@app.route("/contact/<int:contact_id>/unarchive", methods=["POST"])
@login_required
def unarchive_contact(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    contact.archived = False

    db.session.commit()

    return redirect("/contacts?archived=1")

def normalize_lawmatics_money(value):
    return parse_float(value)


def normalize_lawmatics_date(value):
    raw = normalize_text(value)

    if not raw:
        return ""

    try:
        parsed = datetime.strptime(raw, "%m/%d/%Y")
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass

    try:
        parsed = datetime.strptime(raw, "%m/%d/%y")
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass

    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass

    return raw


def make_lawmatics_import_reference(payment):
    parts = [
        payment.get("payment_date", ""),
        payment.get("contact_name", ""),
        payment.get("matter_name", ""),
        str(payment.get("amount", "")),
        payment.get("payment_method", "")
    ]

    raw = "-".join(parts).lower()
    cleaned = ""

    for char in raw:
        if char.isalnum():
            cleaned += char
        else:
            cleaned += "-"

    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")

    return "LM-TRUST-" + cleaned.strip("-")


def parse_lawmatics_trust_ledger_text(raw_text):
    text = raw_text or ""

    text = text.replace("\r", "\n")
    text = text.replace("\t", "\n")

    lines = []

    for line in text.split("\n"):
        cleaned = normalize_text(line)
        if cleaned:
            lines.append(cleaned)

    rows = []
    column_count = 11

    for index in range(0, len(lines)):
        chunk = lines[index:index + column_count]

        if len(chunk) < column_count:
            continue

        date_value = chunk[0]

        looks_like_date = (
            "/" in date_value or
            "-" in date_value
        )

        if not looks_like_date:
            continue

        credit_amount = normalize_lawmatics_money(chunk[8])

        if credit_amount <= 0:
            continue

        payment = {
            "payment_date": normalize_lawmatics_date(chunk[0]),
            "status": chunk[1],
            "invoice": chunk[2],
            "contact_name": chunk[3],
            "matter_name": chunk[4],
            "billing_type": chunk[5],
            "payment_method": chunk[6],
            "entered_by": chunk[7],
            "amount": credit_amount,
            "debit": normalize_lawmatics_money(chunk[9]),
            "balance": normalize_lawmatics_money(chunk[10]),
        }

        payment["reference"] = make_lawmatics_import_reference(payment)

        notes = []
        if payment["billing_type"]:
            notes.append("Billing Type: " + payment["billing_type"])
        if payment["payment_method"]:
            notes.append("Payment Method: " + payment["payment_method"])
        if payment["entered_by"]:
            notes.append("Entered By: " + payment["entered_by"])
        if payment["invoice"]:
            notes.append("Invoice: " + payment["invoice"])
        if payment["status"]:
            notes.append("Status: " + payment["status"])

        payment["notes"] = " | ".join(notes)

        already_seen = False
        for existing in rows:
            if existing["reference"] == payment["reference"]:
                already_seen = True

        if not already_seen:
            rows.append(payment)

    rows.sort(key=lambda item: item.get("payment_date") or "", reverse=True)

    return rows


def find_case_for_lawmatics_payment(payment, client=None):
    matter_name = normalize_text(payment.get("matter_name"))

    if matter_name:
        case = Case.query.filter(Case.case_name.contains(matter_name)).first()
        if case:
            return case

    if client:
        case = Case.query.filter_by(client_id=client.id).first()
        if case:
            return case

    contact_name = normalize_text(payment.get("contact_name"))

    if contact_name:
        case = Case.query.filter(Case.client_name.contains(contact_name)).first()
        if case:
            return case

    return None


def import_lawmatics_trust_payment(payment):
    reference = payment.get("reference") or make_lawmatics_import_reference(payment)

    existing = TrustPayment.query.filter_by(
        lawmatics_transaction_id=reference
    ).first()

    if existing:
        return {
            "status": "duplicate",
            "reference": reference,
            "payment": payment
        }

    client = get_or_create_client_from_name(payment.get("contact_name"))

    case = find_case_for_lawmatics_payment(payment, client)

    if case and not case.client_id and client:
        case.client_id = client.id

    trust_payment = TrustPayment(
        trust_payment_reference=reference,
        payment_date=payment.get("payment_date"),
        client_id=client.id if client else None,
        case_id=case.id if case else None,
        amount=parse_float(payment.get("amount")),
        payment_source="Lawmatics",
        lawmatics_transaction_id=reference,
        status="Completed",
        notes=payment.get("notes")
    )

    db.session.add(trust_payment)

    ledger_entry = TrustLedgerEntry(
        reference_number=reference,
        transaction_date=payment.get("payment_date"),
        client_id=client.id if client else None,
        case_id=case.id if case else None,
        transaction_type="Deposit",
        amount=parse_float(payment.get("amount")),
        notes="Imported from Lawmatics Trust Account Ledger. " + (payment.get("notes") or ""),
        entered_by_id=current_user.id if current_user.is_authenticated else None
    )

    db.session.add(ledger_entry)

    if case:
        refresh_case_financials(case)

    return {
        "status": "created",
        "reference": reference,
        "client_name": client.client_name if client else "",
        "case_name": case.case_name if case else "",
        "payment": payment
    }


@app.route("/trust", methods=["GET"])
@login_required
def trust_dashboard():
    trust_payments = TrustPayment.query.order_by(
        TrustPayment.payment_date.desc()
    ).all()

    trust_ledger_entries = TrustLedgerEntry.query.order_by(
        TrustLedgerEntry.transaction_date.desc()
    ).all()

    cases = Case.query.all()

    for case in cases:
        refresh_case_financials(case)

    db.session.commit()

    return render_template(
        "trust.html",
        trust_payments=trust_payments,
        trust_ledger_entries=trust_ledger_entries,
        cases=cases
    )


@app.route("/lawmatics/trust-import", methods=["GET"])
@login_required
def lawmatics_trust_import():
    return render_template(
        "lawmatics_trust_import.html",
        parsed_payments=None,
        import_results=None,
        raw_text=""
    )


@app.route("/lawmatics/trust-import/preview", methods=["POST"])
@login_required
def lawmatics_trust_import_preview():
    raw_text = request.form.get("ledger_text") or ""
    parsed_payments = parse_lawmatics_trust_ledger_text(raw_text)

    return render_template(
        "lawmatics_trust_import.html",
        parsed_payments=parsed_payments,
        import_results=None,
        raw_text=raw_text
    )

@app.route("/lawmatics/trust-import/run", methods=["POST"])
@login_required
def lawmatics_trust_import_run():
    raw_text = request.form.get("ledger_text") or ""
    parsed_payments = parse_lawmatics_trust_ledger_text(raw_text)

    import_results = []

    for payment in parsed_payments:
        result = import_lawmatics_trust_payment(payment)
        import_results.append(result)

    db.session.commit()

    return render_template(
        "lawmatics_trust_import.html",
        parsed_payments=parsed_payments,
        import_results=import_results,
        raw_text=raw_text
    )

@app.route("/reports", methods=["GET"])
@login_required
def reports():
    total_cases = Case.query.count()
    open_cases = Case.query.filter_by(status="Open").count()
    closed_cases = Case.query.filter_by(status="Closed").count()

    total_tasks = Task.query.count()
    open_tasks = Task.query.filter_by(completed=False).count()
    completed_tasks = Task.query.filter_by(completed=True).count()

    total_contacts = Contact.query.count()
    active_contacts = Contact.query.filter_by(archived=False).count()
    archived_contacts = Contact.query.filter_by(archived=True).count()

    total_events = CalendarEvent.query.count()

    return render_template(
        "reports.html",
        total_cases=total_cases,
        open_cases=open_cases,
        closed_cases=closed_cases,
        total_tasks=total_tasks,
        open_tasks=open_tasks,
        completed_tasks=completed_tasks,
        total_contacts=total_contacts,
        active_contacts=active_contacts,
        archived_contacts=archived_contacts,
        total_events=total_events
    )


@app.route("/reports/cases", methods=["GET"])
@login_required
def case_report():
    q = request.args.get("q") or None
    status = request.args.get("status") or None
    export = request.args.get("export") or None

    query = Case.query

    if status:
        query = query.filter_by(status=status)

    if q:
        query = query.filter(
            Case.case_name.contains(q) |
            Case.client_name.contains(q) |
            Case.case_number.contains(q) |
            Case.stage.contains(q)
        )

    cases = query.order_by(Case.case_name.asc()).all()

    if export == "csv":
        rows = []

        for case in cases:
            rows.append([
                case.case_name,
                case.client_name,
                case.case_number,
                case.stage,
                case.status
            ])

        return csv_response(
            "case_report.csv",
            ["Case Name", "Client", "Case Number", "Stage", "Status"],
            rows
        )

    return render_template(
        "report_cases.html",
        cases=cases,
        q=q,
        status=status
    )


@app.route("/reports/contacts", methods=["GET"])
@login_required
def contact_report():
    q = request.args.get("q") or None
    contact_type = request.args.get("contact_type") or None
    archived = request.args.get("archived") or None
    export = request.args.get("export") or None

    query = Contact.query

    if contact_type:
        query = query.filter_by(contact_type=contact_type)

    if archived == "1":
        query = query.filter_by(archived=True)
    elif archived == "0":
        query = query.filter_by(archived=False)

    if q:
        query = query.filter(
            Contact.first_name.contains(q) |
            Contact.last_name.contains(q) |
            Contact.company_name.contains(q) |
            Contact.email.contains(q) |
            Contact.phone.contains(q)
        )

    contacts = query.order_by(
        Contact.last_name.asc(),
        Contact.first_name.asc(),
        Contact.company_name.asc()
    ).all()

    if export == "csv":
        rows = []

        for contact in contacts:
            rows.append([
                contact.contact_type,
                contact.first_name,
                contact.last_name,
                contact.company_name,
                contact.email,
                contact.phone,
                contact.contact_group,
                contact.contact_role,
                "Archived" if contact.archived else "Active"
            ])

        return csv_response(
            "contact_report.csv",
            [
                "Type",
                "First Name",
                "Last Name",
                "Company",
                "Email",
                "Phone",
                "Group",
                "Role",
                "Status"
            ],
            rows
        )

    return render_template(
        "report_contacts.html",
        contacts=contacts,
        q=q,
        contact_type=contact_type,
        archived=archived
    )


@app.route("/reports/events", methods=["GET"])
@login_required
def event_report():
    q = request.args.get("q") or None
    event_type = request.args.get("event_type") or None
    export = request.args.get("export") or None

    query = CalendarEvent.query

    if event_type:
        query = query.filter_by(event_type=event_type)

    if q:
        query = query.filter(
            CalendarEvent.title.contains(q) |
            CalendarEvent.location.contains(q) |
            CalendarEvent.description.contains(q)
        )

    events = query.order_by(
        CalendarEvent.event_date.asc(),
        CalendarEvent.start_time.asc()
    ).all()

    if export == "csv":
        rows = []

        for event in events:
            rows.append([
                event.title,
                event.event_type,
                event.event_date,
                event.start_time,
                event.end_time,
                event.location,
                event.case.case_name if event.case else "",
                event.assigned_user.name if event.assigned_user else "",
                "Private" if event.is_private else "Visible"
            ])

        return csv_response(
            "event_report.csv",
            [
                "Title",
                "Type",
                "Date",
                "Start",
                "End",
                "Location",
                "Matter",
                "Assigned User",
                "Visibility"
            ],
            rows
        )

    event_types = [
        "Court Appearance",
        "Deadline",
        "Meeting",
        "Staff Meeting",
        "Client Meeting",
        "Deposition",
        "Hearing",
        "Trial",
        "Reminder",
        "Other"
    ]

    return render_template(
        "report_events.html",
        events=events,
        q=q,
        event_type=event_type,
        event_types=event_types
    )

@app.route("/dev/backfill_case_contacts")
@login_required
def backfill_case_contacts():
    if current_user.role != "admin":
        return "Access denied"

    cases = Case.query.all()

    created_or_updated_count = 0

    for case in cases:
        if case.client_name:
            sync_client_contact_for_case(case)
            created_or_updated_count += 1

    db.session.commit()

    return f"""
    <h1>Backfill Complete</h1>
    <p>Client contacts synced for {created_or_updated_count} matters.</p>
    <p><a href="/contacts">Go to Contacts</a></p>
    """

with app.app_context():
    db.create_all()
    ensure_admin_user()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

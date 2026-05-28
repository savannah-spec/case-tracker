from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(50), default="staff")

class Case(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    mycase_id = db.Column(db.String(100), unique=True, nullable=False)
    case_number = db.Column(db.String(100))
    case_name = db.Column(db.String(250))
    client_name = db.Column(db.String(250))
    stage = db.Column(db.String(100))
    status = db.Column(db.String(100), default="Open")

    document_source = db.Column(db.String(50), default="Not set")
    document_location = db.Column(db.String(500))

    summary = db.Column(db.Text)

    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=True)

    billing_status = db.Column(db.String(100), default="Unbilled")
    trust_balance = db.Column(db.Float, default=0)
    minimum_trust_threshold = db.Column(db.Float, default=0)
    trust_status = db.Column(db.String(100), default="Adequately Funded")

    outstanding_ar = db.Column(db.Float, default=0)
    effective_hourly_value = db.Column(db.Float, default=0)

    total_amount_billed = db.Column(db.Float, default=0)
    total_amount_paid = db.Column(db.Float, default=0)
    total_hours_worked = db.Column(db.Float, default=0)
    billable_hours = db.Column(db.Float, default=0)
    non_billable_hours = db.Column(db.Float, default=0)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=True)

    parent_task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=True)

    assigned_to_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    title = db.Column(db.String(200), nullable=True)

    description = db.Column(db.Text, nullable=True)

    due_date = db.Column(db.String(50), nullable=True)

    priority = db.Column(db.String(50), default="Normal")

    status = db.Column(db.String(50), default="Not Started")

    completed = db.Column(db.Boolean, default=False)

    sort_order = db.Column(db.Integer, default=0)

    case = db.relationship("Case", backref="tasks")

    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])

    subtasks = db.relationship(
        "Task",
        backref=db.backref("parent_task", remote_side=[id])
    )

class CalendarEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    event_type = db.Column(db.String(100), default="Event")

    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    event_date = db.Column(db.String(50), nullable=False)
    start_time = db.Column(db.String(50), nullable=True)
    end_time = db.Column(db.String(50), nullable=True)

    all_day = db.Column(db.Boolean, default=False)
    repeats = db.Column(db.String(100), default="Does not repeat")

    location = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)

    reminder_method = db.Column(db.String(50), default="None")
    reminder_minutes = db.Column(db.Integer, nullable=True)

    is_private = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    case = db.relationship("Case", foreign_keys=[case_id], backref="calendar_events")
    assigned_user = db.relationship("User", foreign_keys=[assigned_user_id], backref="calendar_events")
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])


class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    contact_type = db.Column(db.String(50), default="Person")
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    company_name = db.Column(db.String(200), nullable=True)

    email = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(100), nullable=True)
    address = db.Column(db.Text, nullable=True)

    contact_group = db.Column(db.String(100), nullable=True)
    contact_role = db.Column(db.String(100), nullable=True)

    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=True)

    notes = db.Column(db.Text, nullable=True)
    archived = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    case = db.relationship("Case", foreign_keys=[case_id], backref="linked_contacts")

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    client_name = db.Column(db.String(300), nullable=False)
    email = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(100), nullable=True)
    address = db.Column(db.Text, nullable=True)

    client_type = db.Column(db.String(100), default="Individual")
    status = db.Column(db.String(100), default="Active")
    client_notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    matters = db.relationship("Case", backref="client_record", lazy=True)


class TimeEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    entry_name = db.Column(db.String(300), nullable=True)
    date = db.Column(db.String(50), nullable=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=True)

    hours_worked = db.Column(db.Float, default=0)
    billing_category = db.Column(db.String(150), nullable=True)
    description = db.Column(db.Text, nullable=True)
    billable_status = db.Column(db.String(100), default="Billable")

    user_rate = db.Column(db.Float, default=0)
    case_rate_override = db.Column(db.Float, nullable=True)
    hourly_rate_applied = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float, default=0)

    invoice_status = db.Column(db.String(100), default="Not Invoiced")
    billed_date = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id])
    case = db.relationship("Case", foreign_keys=[case_id], backref="time_entries")


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    invoice_number = db.Column(db.String(100), unique=True, nullable=False)

    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=True)

    invoice_date = db.Column(db.String(50), nullable=True)
    due_date = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(100), default="Draft")

    subtotal = db.Column(db.Float, default=0)
    tax = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float, default=0)
    amount_paid = db.Column(db.Float, default=0)

    payment_method = db.Column(db.String(100), nullable=True)
    square_payment_id = db.Column(db.String(200), nullable=True)

    paid_from_trust = db.Column(db.Boolean, default=False)
    trust_transfer_amount = db.Column(db.Float, default=0)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    case = db.relationship("Case", foreign_keys=[case_id], backref="invoices")
    client = db.relationship("Client", foreign_keys=[client_id], backref="invoices")


class TrustPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    trust_payment_reference = db.Column(db.String(200), unique=True, nullable=False)
    payment_date = db.Column(db.String(50), nullable=True)

    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=True)

    amount = db.Column(db.Float, default=0)
    payment_source = db.Column(db.String(100), default="Lawmatics")
    lawmatics_transaction_id = db.Column(db.String(200), nullable=True)

    status = db.Column(db.String(100), default="Completed")
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client = db.relationship("Client", foreign_keys=[client_id], backref="trust_payments")
    case = db.relationship("Case", foreign_keys=[case_id], backref="trust_payments")


class TrustLedgerEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    reference_number = db.Column(db.String(200), unique=True, nullable=False)

    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=True)

    transaction_date = db.Column(db.String(50), nullable=True)
    transaction_type = db.Column(db.String(100), default="Deposit")
    amount = db.Column(db.Float, default=0)

    notes = db.Column(db.Text, nullable=True)

    entered_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    related_invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    case = db.relationship("Case", foreign_keys=[case_id], backref="trust_ledger_entries")
    client = db.relationship("Client", foreign_keys=[client_id], backref="trust_ledger_entries")
    entered_by = db.relationship("User", foreign_keys=[entered_by_id])
    related_invoice = db.relationship("Invoice", foreign_keys=[related_invoice_id])


class BillingRate(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    billing_rate_entry = db.Column(db.String(300), nullable=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=True)

    default_hourly_rate = db.Column(db.Float, default=0)
    effective_date = db.Column(db.String(50), nullable=True)
    matter_specific_rate_override = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id], backref="billing_rates")
    case = db.relationship("Case", foreign_keys=[case_id], backref="billing_rates")

from flask_login import UserMixin

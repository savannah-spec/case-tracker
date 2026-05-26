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

from flask_login import UserMixin
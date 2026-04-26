from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

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
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"))
    description = db.Column(db.String(500))
    completed = db.Column(db.Boolean, default=False)
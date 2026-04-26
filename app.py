from pypdf import PdfReader
from docx import Document
import os
from openai import OpenAI

from flask import Flask, request, redirect
from models import db, Case, Task
import csv
import io
import json

app = Flask(__name__)
client = OpenAI()

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///cases.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


@app.route("/")
def home():
    cases = Case.query.all()

    html = """
    <h1>Law Firm Case Tracker</h1>

    <h2>Upload Updated MyCase CSV</h2>
    <form method="POST" action="/upload_csv" enctype="multipart/form-data">
        <input type="file" name="csv_file" accept=".csv">
        <button type="submit">Upload CSV</button>
    </form>

    <h2>Cases</h2>
    """

    for case in cases:
        tasks = Task.query.filter_by(case_id=case.id).all()

        html += f"""
        <div style="border:1px solid #ccc; padding:10px; margin:10px;">
            <strong>{case.case_name}</strong><br>
            MyCase ID: {case.mycase_id}<br>
            Case Number: {case.case_number}<br>
            Client: {case.client_name}<br>
            Stage: {case.stage}<br>
            Status: {case.status}<br>
            Document Location: {case.document_location}<br>

            <form method="POST" action="/update_document_source/{case.id}">
                <p>Folder Path:</p>
                <input name="document_location" style="width:400px">
                <button type="submit">Save</button>
            </form>

            <form method="POST" action="/summarize_case/{case.id}">
                <button type="submit">Summarize Documents</button>
            </form>

            <p><strong>Summary:</strong></p>
            <pre>{case.summary or "No summary yet."}</pre>

            <p><strong>Tasks:</strong></p>
        """

        if tasks:
            html += "<ul>"
            for task in tasks:
                checked = "checked" if task.completed else ""
                html += f"""
                <li>
                    <form method="POST" action="/toggle_task/{task.id}" style="display:inline;">
                        <input type="checkbox" onchange="this.form.submit()" {checked}>
                        {task.description}
                    </form>
                </li>
                """
            html += "</ul>"
        else:
            html += "<p>No tasks yet.</p>"

        html += "</div>"

    return html


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
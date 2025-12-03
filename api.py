from flask import Flask, jsonify, request, g
import sqlite3
import os
from datetime import datetime, timedelta
from flask_cors import CORS # Used to allow your HTML/JS file to access this API

app = Flask(__name__)
CORS(app) # Enable CORS for cross-origin requests from your HTML file
DATABASE = 'medicas.db' # Or 'database.sqlite' if you rename the file

# --- Database Connection Management ---

def get_db():
    """Connects to the specified database."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row # Allows accessing columns by name
    return db

@app.teardown_appcontext
def close_connection(exception):
    """Closes the database connection when the application context ends."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- Utility Function to run initial database setup (from your provided code) ---

def init_db():
    """Initializes the database with tables and doctors if they don't exist."""
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        # 1. Create the Doctors Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS doctors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                specialty TEXT NOT NULL
            )
        ''')

        # 2. Create the Appointments Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_id TEXT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                is_booked INTEGER DEFAULT 0,
                patient_id TEXT,
                FOREIGN KEY (doctor_id) REFERENCES doctors(id)
            )
        ''')

        # 3. Insert Initial Doctors Data
        doctors_data = [
            ('DR_PIYUSH_GUPTA', 'Dr. Piyush Gupta', 'Dermatology'),
            ('DR_K_PATEL_GP', 'Dr. K. Patel', 'General Physician'),
            ('DR_M_MOHAN', 'Dr. M. Mohan', 'Pediatrics'),
            ('DR_RK_SHARMA', 'Dr. RK. Sharma', 'Obstetrics Gynecology')
        ]
        # Insert or ignore doctors, in case the script runs multiple times
        cursor.executemany("INSERT OR IGNORE INTO doctors VALUES (?, ?, ?)", doctors_data)
        
        # 4. Insert Initial Appointment Slots (Mock Data Generation)
        # This simulates fixed availability for the next few days.
        today = datetime.now().date()
        slots_to_insert = []
        for i in range(1, 4):  # Next 3 days
            date_str = (today + timedelta(days=i)).strftime('%Y-%m-%d')
            for doc_id in [d[0] for d in doctors_data]:
                # Generate two slots per doctor per day
                slots_to_insert.append((doc_id, date_str, "09:00 AM", 0, None))
                slots_to_insert.append((doc_id, date_str, "04:00 PM", 0, None))
        
        # Insert initial available slots
        insert_slot_sql = "INSERT INTO appointments (doctor_id, date, time, is_booked, patient_id) VALUES (?, ?, ?, ?, ?)"
        
        # Check if slots exist before inserting (avoids duplicates without relying on complex logic)
        for doc_id, date_str, time_str, is_booked, patient_id in slots_to_insert:
            cursor.execute("SELECT COUNT(*) FROM appointments WHERE doctor_id = ? AND date = ? AND time = ?", (doc_id, date_str, time_str))
            if cursor.fetchone()[0] == 0:
                 cursor.execute(insert_slot_sql, (doc_id, date_str, time_str, is_booked, patient_id))

        db.commit()
        print("Database structure and initial data checked/created.")


# --- API Endpoints ---

@app.route('/api/slots', methods=['GET'])
def get_slots():
    """Retrieves available slots for a given specialty."""
    specialty = request.args.get('specialty')
    db = get_db()
    
    # 1. Get the Doctor ID based on specialty
    doc_row = db.execute("SELECT id, name FROM doctors WHERE specialty = ?", (specialty,)).fetchone()
    if not doc_row:
        return jsonify({"slots": []})

    doctor_id = doc_row['id']
    
    # 2. Retrieve unbooked slots for that doctor
    # Filters slots for today and the future
    today_str = datetime.now().date().strftime('%Y-%m-%d')
    
    slots_query = """
        SELECT id, date, time 
        FROM appointments 
        WHERE doctor_id = ? AND is_booked = 0 AND date >= ? 
        ORDER BY date, time 
        LIMIT 6
    """
    slots_rows = db.execute(slots_query, (doctor_id, today_str)).fetchall()

    slots_list = []
    for row in slots_rows:
        slots_list.append({
            "id": row['id'],
            "date": row['date'],
            "time": row['time'],
            "day": datetime.strptime(row['date'], '%Y-%m-%d').strftime('%A'), # Add day of the week
            "is_best_match": len(slots_list) == 0, # Simple mock logic: first slot is "best"
            "doctorId": doctor_id,
            "doctorName": doc_row['name']
        })

    return jsonify({"slots": slots_list})


@app.route('/api/book', methods=['POST'])
def book_appointment():
    """Books a specific slot by updating the appointments table."""
    data = request.get_json()
    slot_id = data.get('slot_id')
    patient_id = data.get('patient_id', 'WEB_USER') # Use a default or the actual user ID

    if not slot_id:
        return jsonify({"message": "Slot ID required"}), 400

    db = get_db()
    cursor = db.cursor()

    try:
        # Attempt to mark the slot as booked
        cursor.execute(
            "UPDATE appointments SET is_booked = 1, patient_id = ? WHERE id = ? AND is_booked = 0",
            (patient_id, slot_id)
        )
        db.commit()

        if cursor.rowcount == 0:
            return jsonify({"message": "Slot is already booked or does not exist."}), 409
        
        return jsonify({"message": "Appointment successfully booked", "appointment_id": slot_id}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"message": f"Database error: {e}"}), 500


if __name__ == '__main__':
    # Initialize DB (creates medicas.db and tables if missing)
    init_db()
    # Run the Flask app
    # In a production environment, you would use a dedicated web server like Gunicorn
    app.run(host='0.0.0.0', port=5000, debug=True)
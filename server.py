from flask import Flask, render_template, request, redirect, session, url_for
from pymongo import MongoClient
from flask_pymongo import PyMongo
from werkzeug.utils import secure_filename
import serial
import os
import time
import cv2
import face_recognition
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Connect to MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['your_database_name']
users_collection = db['users']
missing_persons_collection = db['missing_persons']

# Function to fetch registered user email
def get_registered_user_email():
    if 'username' in session:
        user = users_collection.find_one({'username': session['username']})
        if user and 'email' in user:
            return user['email']
    print("Unable to fetch registered user email from the current session.")
    return None



# Email configuration
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USERNAME = 'karthickr45161@gmail.com'
SMTP_PASSWORD = 'vbwr iabv rgnr kqla'
SENDER_EMAIL = 'ravikarthik138@gmail.com'
REGISTERED_USER_EMAIL = None  # Initialize the variable to None

# Function to fetch registered user email
def get_registered_user_email():
    if 'username' in session:
        user = users_collection.find_one({'username': session['username']})
        if user and 'email' in user:
            return user['email']
    print("Unable to fetch registered user email from the current session.")
    return None


# Configure upload folder
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Configure detected images folder
DETECTED_IMAGES_FOLDER = 'static/detected_images'
if not os.path.exists(DETECTED_IMAGES_FOLDER):
    os.makedirs(DETECTED_IMAGES_FOLDER)
app.config['DETECTED_IMAGES_FOLDER'] = DETECTED_IMAGES_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def read_gps_data(serial_port='COM4', baud_rate=9600):
    ser = serial.Serial(serial_port, baud_rate)
    try:
        for line in ser:
            line = line.decode('latin-1').strip()
            if line.startswith("Latitude:") or line.startswith("Longitude:"):
                yield line
    except KeyboardInterrupt:
        ser.close()

# Routes
@app.route('/')
def index():
    return render_template('home.html')

@app.route('/find')
def home():
    return render_template('find.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/service')
def services():
    return render_template('service.html')

@app.route('/why-us')
def why_us():
    return render_template('why.html')

@app.route('/team')
def team():
    return render_template('team.html')




@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        # Check if username or email already exists in the database
        if users_collection.find_one({'$or': [{'username': username}, {'email': email}]}):
            error = "Username or email already exists!"
        else:
            # Insert new user data into the database
            user_data = {'username': username, 'email': email, 'password': password}
            users_collection.insert_one(user_data)
            return redirect('/login')

    return render_template('register.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Query the database to find the user by email
        user = users_collection.find_one({'email': email})

        if user and user['password'] == password:
            session['username'] = user['username']  # Store the username in the session
            return redirect('/missing_person_form')
        else:
            error = "Invalid email or password"

    return render_template('login.html', error=error)


@app.route('/missing_person_form')
def missing_person_form():
    global REGISTERED_USER_EMAIL
    REGISTERED_USER_EMAIL = get_registered_user_email()  # Fetch the registered user email dynamically
    if 'username' in session:
        return render_template('missing_person_form.html', username=session['username'])
    else:
        return redirect('/login')

# Define the route for submitting missing person details
@app.route('/submit', methods=['POST'])
def submit():
    if request.method == 'POST':
        # Extract missing person details from the form
        name = request.form['fullName']
        age = request.form['age']
        gender = request.form['gender']
        last_seen_location = request.form['lastSeenLocation']
        date_missing = request.form['dateMissing']
        contact_info = request.form['contactInfo']
        additional_info = request.form['additionalInfo']

        # Read latitude and longitude from GPS serial port
        latitude, longitude = None, None
        for data in read_gps_data():
            if data.startswith("Latitude:"):
                latitude = data.split(":")[1].strip()
            elif data.startswith("Longitude:"):
                longitude = data.split(":")[1].strip()
            if latitude is not None and longitude is not None:
                break

        # Check if the request contains the file part
        if 'photo' in request.files:
            file = request.files['photo']

            # If the file is valid and allowed
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)

                # Save missing person details to MongoDB
                missing_person_data = {
                    'name': name,
                    'age': age,
                    'gender': gender,
                    'last_seen_location': last_seen_location,
                    'date_missing': date_missing,
                    'contact_info': contact_info,
                    'additional_info': additional_info,
                    'latitude': latitude,
                    'longitude': longitude,
                    'image': os.path.join('uploads', filename),
                    'username': session['username']  # Associate the missing person with the logged-in user
                }
                missing_persons_collection.insert_one(missing_person_data)

                # Detect faces and send email if a face is found
                known_faces, known_names = load_known_faces("uploads")
                face_found, detected_image_path = detect_and_compare_faces(known_faces, known_names, filename)

                if face_found:
                    # Send email with additional information
                    send_email(name, file_path, detected_image_path, additional_info, latitude, longitude)

                    # Redirect to missing_person_found route
                    return redirect(url_for('missing_person_found'))

    return "Face detection completed!"
# Route to display missing persons details
@app.route('/details')
def missing_persons_details():
    # Retrieve missing persons associated with the logged-in user
    missing_persons = missing_persons_collection.find({'username': session['username']})

    # Pass the data to the template
    return render_template('details.html', missing_persons=missing_persons)

# Route to display missing persons details
@app.route('/missing_person_details')
def missing_person_details():
    return redirect(url_for('missing_persons_details_page'))



@app.route('/missing_person_found')
def missing_person_found():
    # Assuming missing_persons is a list of dictionaries retrieved from MongoDB
    missing_persons = missing_persons_collection.find({'username': session['username']})  # Retrieve missing persons associated with the logged-in user

    # Read latitude and longitude from GPS serial port
    latitude, longitude = None, None
    for data in read_gps_data():
        if data.startswith("Latitude:"):
            latitude = data.split(":")[1].strip()
        elif data.startswith("Longitude:"):
            longitude = data.split(":")[1].strip()
        if latitude is not None and longitude is not None:
            break

    # Pass the data to the template
    detected_image = os.path.join(app.config['DETECTED_IMAGES_FOLDER'], 'detected_image.jpg')
    google_maps_link = create_google_maps_link(latitude, longitude)
    return render_template('missing_person_found.html', missing_persons=missing_persons, detected_image=detected_image, google_maps_link=google_maps_link)

# Function to load known faces from directory
def load_known_faces(directory):
    known_faces = []
    known_names = []

    for filename in os.listdir(directory):
        if filename.endswith(".jpg") or filename.endswith(".png"):
            image_path = os.path.join(directory, filename)
            face_image = face_recognition.load_image_file(image_path)
            face_encoding = face_recognition.face_encodings(face_image)[0]
            known_faces.append(face_encoding)
            known_names.append(os.path.splitext(filename)[0])

    return known_faces, known_names

# Function to detect and compare faces
def detect_and_compare_faces(known_faces, known_names, uploaded_filename):
    # Set the desired resolution
    capture_width = 600
    capture_height = 500

    # Open the camera with the desired resolution
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, capture_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, capture_height)

    face_found = False
    start_time = time.time()
    duration = 15  # Detection duration in seconds
    detected_image_path = os.path.join(app.config['DETECTED_IMAGES_FOLDER'], 'detected_image.jpg')

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_frame)
        face_landmarks_list = face_recognition.face_landmarks(rgb_frame)

        if face_locations:
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

            for face_encoding, (top, right, bottom, left), landmarks in zip(face_encodings, face_locations, face_landmarks_list):
                matches = face_recognition.compare_faces(known_faces, face_encoding)

                if True in matches:
                    face_found = True
                    name = known_names[matches.index(True)]

                    face_distances = face_recognition.face_distance(known_faces, face_encoding)
                    percentage_matching = (1 - min(face_distances)) * 100

                    # Draw rectangle around the detected face
                    cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)

                    # Draw spots on the face for facial landmarks
                    for facial_feature in landmarks.keys():
                        for point in landmarks[facial_feature]:
                            cv2.circle(frame, point, 2, (0, 0, 255), -1)

                    # Display the name and percentage of matching
                    label = f"{name} ({percentage_matching:.2f}%)"
                    cv2.putText(frame, label, (left + 6, bottom - 6), cv2.FONT_HERSHEY_DUPLEX, 0.5, (255, 255, 255), 1)

                    # Save detected image
                    cv2.imwrite(detected_image_path, frame)

                    break

        cv2.imshow('Face Detection', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        # Check if the duration has passed
        if time.time() - start_time > duration:
            break

    cap.release()
    cv2.destroyAllWindows()

    return face_found, detected_image_path

import smtplib
import traceback  # Import traceback module for error handling

# Function to send email
def send_email(name, uploaded_image_path, detected_image_path, details, latitude, longitude):
    try:
        # Fetch the registered user email dynamically
        registered_user_email = get_registered_user_email()

        # Check if the registered user email is available
        if registered_user_email:
            # Setup the MIME
            message = MIMEMultipart()
            message['From'] = SENDER_EMAIL
            message['To'] = registered_user_email
            message['Subject'] = 'Missing Person Alert'

            # Get current date and time
            current_datetime = time.strftime("%Y-%m-%d %H:%M:%S")

            # Generate Google Maps link
            google_maps_link = create_google_maps_link(latitude, longitude)

            # The body of the email
            body = f"Hello,\n\n{name} has been detected as a missing person. Please take necessary actions.\n\nDetails: {details}\n\nDate: {current_datetime}\n\nGoogle Maps Link: {google_maps_link}"

            # Attach the body to the email
            message.attach(MIMEText(body, 'plain'))

            # Attach the uploaded image
            with open(uploaded_image_path, 'rb') as attachment:
                uploaded_image_data = attachment.read()

            uploaded_image_attachment = MIMEImage(uploaded_image_data, name=os.path.basename(uploaded_image_path))
            message.attach(uploaded_image_attachment)

            # Attach the detected image
            with open(detected_image_path, 'rb') as attachment:
                detected_image_data = attachment.read()

            detected_image_attachment = MIMEImage(detected_image_data, name=os.path.basename(detected_image_path))
            message.attach(detected_image_attachment)

            # Connect to the server
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()

            # Login to the server
            server.login(SMTP_USERNAME, SMTP_PASSWORD)

            # Send the email
            server.sendmail(SENDER_EMAIL, registered_user_email, message.as_string())

            # Quit the server
            server.quit()
        else:
            print("Registered user email not found. Unable to send email.")
    except Exception as e:
        # Handle exceptions
        print("An error occurred while sending email:")
        print(traceback.format_exc())  # Print traceback for debugging

# Function to create Google Maps link
def create_google_maps_link(latitude, longitude):
    return f"https://www.google.com/maps?q={latitude},{longitude}"

if __name__ == '__main__':
    app.run(debug=True)


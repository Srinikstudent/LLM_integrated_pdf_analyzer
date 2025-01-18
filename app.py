import os
import json
import shutil
from flask import Flask, request, jsonify, send_from_directory, render_template
from gen_ai import gen_ai
import requests
from urllib.parse import urlparse


app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
METADATA_FILE = 'metadata.json'

def ensure_metadata():
    if not os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'w') as f:
            json.dump({}, f)

ensure_metadata()

def load_metadata():
    with open(METADATA_FILE, 'r') as f:
        return json.load(f)

def save_metadata(metadata):
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=4)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files.get('file')
    pdf_url = request.form.get('url', '').strip()
    directory = request.form.get('directory', '').strip()

    if not directory:
        return jsonify({'error': 'No directory specified'}), 400

    save_dir = os.path.join(app.config['UPLOAD_FOLDER'], directory)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    if file:
        file_path = os.path.join(save_dir, file.filename)
        file.save(file_path)
    elif pdf_url:
        try:
            response = requests.get(pdf_url)
            if response.status_code == 200:
                file_name = os.path.basename(urlparse(pdf_url).path)
                file_path = os.path.join(save_dir, file_name)
                with open(file_path, 'wb') as f:
                    f.write(response.content)
            else:
                return jsonify({'error': 'Failed to download the file from the URL'}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 400
    else:
        return jsonify({'error': 'No file or URL provided'}), 400

    metadata = load_metadata()
    metadata[file_path] = {'comments': None, 'gen_ai_output': None}
    save_metadata(metadata)

    return jsonify({'message': 'File uploaded successfully', 'path': file_path}), 200

@app.route('/rename-directory', methods=['POST'])
def rename_directory():
    old_name = request.form.get('old_name', '').strip()
    new_name = request.form.get('new_name', '').strip()

    old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_name)
    new_path = os.path.join(app.config['UPLOAD_FOLDER'], new_name)

    if os.path.exists(old_path):
        os.rename(old_path, new_path)

        metadata = load_metadata()
        updated_metadata = {}
        for key, value in metadata.items():
            if key.startswith(old_path):
                updated_key = key.replace(old_path, new_path, 1)
                updated_metadata[updated_key] = value
            else:
                updated_metadata[key] = value

        save_metadata(updated_metadata)
        return jsonify({'message': 'Directory renamed successfully'}), 200
    else:
        return jsonify({'error': 'Directory does not exist'}), 400

@app.route('/delete-directory/<path:directory>', methods=['DELETE'])
def delete_directory(directory):
    dir_path = os.path.join(app.config['UPLOAD_FOLDER'], directory)

    if os.path.exists(dir_path) and os.path.isdir(dir_path):
        shutil.rmtree(dir_path)

        metadata = load_metadata()
        keys_to_remove = [key for key in metadata if key.startswith(dir_path)]
        for key in keys_to_remove:
            del metadata[key]
        save_metadata(metadata)

        return jsonify({'message': 'Directory deleted successfully'}), 200
    else:
        return jsonify({'error': 'Directory does not exist'}), 400

@app.route('/directories', methods=['GET'])
def list_directories():
    def get_directory_structure(rootdir):
        structure = {}
        for root, dirs, files in os.walk(rootdir):
            rel_path = os.path.relpath(root, rootdir)
            if rel_path == '.':
                rel_path = ''
            structure[rel_path] = {
                'dirs': dirs,
                'files': files,
            }
        return structure

    structure = get_directory_structure(app.config['UPLOAD_FOLDER'])
    return jsonify(structure)

@app.route('/file/<path:filename>')
def serve_file(filename):
    directory = os.path.dirname(filename)
    filename = os.path.basename(filename)
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], directory), filename)

@app.route('/delete/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    metadata = load_metadata()

    if os.path.exists(file_path):
        os.remove(file_path)

        if file_path in metadata:
            comment_file = metadata[file_path].get('comments')
            if comment_file and os.path.exists(comment_file):
                os.remove(comment_file)

            gen_ai_output = metadata[file_path].get('gen_ai_output')
            if gen_ai_output and os.path.exists(gen_ai_output):
                os.remove(gen_ai_output)

            del metadata[file_path]
            save_metadata(metadata)

        return jsonify({'message': 'File deleted successfully'}), 200
    else:
        return jsonify({'error': 'File not found'}), 404

@app.route('/comments/<path:filename>', methods=['POST', 'GET'])
def manage_comments(filename):
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    metadata = load_metadata()

    if request.method == 'POST':
        comment = request.form.get('comment', '')
        comment_file_path = pdf_path.replace('.pdf', '_comments.txt')

        with open(comment_file_path, 'w') as comment_file:
            comment_file.write(comment)

        metadata[pdf_path]['comments'] = comment_file_path
        save_metadata(metadata)

        return jsonify({'message': 'Comment saved successfully', 'comment_file': comment_file_path}), 200

    elif request.method == 'GET':
        if pdf_path in metadata and metadata[pdf_path].get('comments'):
            comment_file_path = metadata[pdf_path]['comments']
            if os.path.exists(comment_file_path):
                with open(comment_file_path, 'r') as comment_file:
                    comments = comment_file.read()
                return jsonify({'comments': comments})
        return jsonify({'comments': ''})

@app.route('/analyze-pdf', methods=['POST'])
def analyze_pdf():
    pdf_path = request.form.get('pdf_path')
    message = request.form.get('message')

    if pdf_path and message:
        try:
            # Call the gen_ai function with the provided PDF path and message
            response = gen_ai(f'uploads/{pdf_path}', message)
            
            # Return the response directly to the frontend
            return jsonify({'response': response}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 400
    else:
        return jsonify({'error': 'PDF path and message are required'}), 400

if __name__ == '__main__':
    app.run(debug=True)

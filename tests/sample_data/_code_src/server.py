from flask import Flask
app = Flask(__name__)

API_KEY = "sk_live_hardcoded_12345"  # TODO: move to secrets store

@app.route('/status')
def status():
    return {'ok': True}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)  # open network listener

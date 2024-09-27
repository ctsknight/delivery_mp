from flask import Flask, jsonify, request
app = Flask(__name__)

@app.route('/price', methods=['POST'])
def get_tasks():
    print(request.get_data())
    return jsonify({'price': 100})

if __name__ == '__main__':
    app.run(debug=True)

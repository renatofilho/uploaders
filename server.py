from flask import Flask, request, jsonify, g
from flask_httpauth import HTTPBasicAuth
from itsdangerous import (
    TimedJSONWebSignatureSerializer as Serializer,
    BadSignature,
    SignatureExpired,
)

# filesystem
from os import listdir, getcwd, path, makedirs
from os.path import isfile, join

import config

app = Flask(__name__)
auth = HTTPBasicAuth()


class FileSystemModel:
    def __init__(self, folder):
        self.path = folder

    def ls(self):
        return [f for f in listdir(self.path) if isfile(join(self.path, f))]

    def upload(self, f):
        f.save(join(self.path, f.filename))


class Session:
    APP_SECRET_KEY = "1234567890"

    def __init__(self):
        self.data = FileSystemModel(join(getcwd(), config.uploadDir))

    @staticmethod
    def verify_auth_token(token):
        s = Serializer(Session.APP_SECRET_KEY)
        try:
            s.loads(token)
        except:
            return None

    def token(self):
        s = Serializer(Session.APP_SECRET_KEY, expires_in=1000)
        return s.dumps({"id": 0})

    def fileSystem():
        return self.data


@auth.verify_password
def verify_password(token, password):
    data = Session.verify_auth_token(token)
    if not data:
        if token == "admin" and password == "secret":
            g.session = Session()
            return True
        else:
            return False
    else:
        return True


@app.route("/api/token")
@auth.login_required
def get_auth_token():
    token = g.session.token()
    return jsonify({"token": token.decode("ascii")})


@app.route("/api/ls")
@auth.login_required
def list_contents():
    files = g.session.data.ls()
    return jsonify({"files": files})


@app.route("/api/upload", methods=["POST"])
@auth.login_required
def upload_file():
    if "file" in request.files:
        print("Found file:", request.files["file"].filename)
        g.session.data.upload(request.files["file"])
        return ("", 201)
    else:
        print("file not present in", request.files.to_dict())
    return ("", 501)


if __name__ == "__main__":
    if not path.exists(config.uploadDir):
        makedirs(config.uploadDir)
    app.run(debug=True)
